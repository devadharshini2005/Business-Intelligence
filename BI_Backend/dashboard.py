"""Analytics page for the IDP (intellidoc) data - read-only, process-centred.

Every number comes from a fixed aggregation built in this module; the only inputs are the scope
(period, source, process), and those only ever become $match values. Each panel is computed on its own,
so one failing query shows as an error on that panel instead of breaking the page.

Panels (the frontend lays them out):
  kpis          headline figures, each with a daily sparkline and the change vs the previous period
  pipeline      documents: received -> processed -> extracted -> completed, and where the rest stopped
  processes     scorecard, one row per process (the rows also drive the process filter)
  trend         runs per day by outcome
  bottlenecks   workflow steps where runs fail or wait (file_process_tracker)
  review_queue  runs waiting for review, oldest first
  by_source     submissions by source
  recent        latest submissions
  insights      sentences templated around the figures above - nothing is written by a model

Dates are stored in UTC; days are counted in India time (IST).
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from bson import ObjectId
from bson.errors import InvalidId

from charts import from_rows
from idp_flow import SOURCES, IdpFlow

SOURCE_LABELS = {"email": "Email", "webhook": "Webhook", "manual_upload": "Manual upload"}

# Users are in India; the database stores UTC. Day buckets use IST so "today" means today in India.
IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")
IST_OFFSET = "+05:30"

DONE = "completed"
REVIEW = "pending_review"
FAILED = "failed"
REJECTED = "rejected"
STUCK_STEP = ["failed", "awaiting_approval", "rejected"]  # file_process_tracker statuses that stop a run
MAX_DAILY_POINTS = 120
PANEL_WORKERS = 4


def _since(days: int) -> dt.datetime | None:
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days) if days > 0 else None


def _ist_midnight(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, IST)


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _delta(cur: float | None, prev: float | None, kind: str) -> float | None:
    """Change vs the previous period: relative for counts, percentage points for rates."""
    if cur is None or prev is None:
        return None
    if kind == "points":
        return round(cur - prev, 1)
    return round((cur - prev) / prev, 3) if prev else None


class Scope:
    """The page's filters. `process` is a process _id; source is one of SOURCES (or empty)."""

    def __init__(self, days: int, source: str, process: str) -> None:
        if source and source not in SOURCES:
            raise ValueError(f"source must be one of {', '.join(SOURCES)} (or empty for all)")
        try:
            self.process = ObjectId(process) if process else None
        except (InvalidId, TypeError):
            raise ValueError("process must be a process id") from None
        self.days, self.source = max(0, int(days)), source
        today = dt.datetime.now(IST).date()
        # A period starts at IST midnight; the previous period is the same length just before it.
        self.start = _ist_midnight(today - dt.timedelta(days=self.days)) if self.days else None
        self.prev_start = _ist_midnight(today - dt.timedelta(days=2 * self.days)) if self.days else None

    def runs(self, start: dt.datetime | None = None, end: dt.datetime | None = None) -> dict[str, Any]:
        """$match for extraction_results in this scope, optionally limited to [start, end)."""
        m: dict[str, Any] = {}
        if start or end:
            m["created_at"] = {k: v for k, v in (("$gte", start), ("$lt", end)) if v}
        if self.source:
            m[SOURCES[self.source]["run_fk"]] = {"$exists": True, "$ne": None}
        if self.process:
            m["proccess_id"] = self.process  # sic - the stored spelling
        return m


class Dashboard:
    def __init__(self, db) -> None:
        self.db = db

    # --- shared queries ----------------------------------------------------------------------
    def _run_totals(self, match: dict[str, Any]) -> dict[str, Any]:
        rows = list(self.db.extraction_results.aggregate([
            {"$match": match},
            {"$group": {
                "_id": None,
                "runs": {"$sum": 1},
                "completed": {"$sum": {"$cond": [{"$eq": ["$status", DONE]}, 1, 0]}},
                "review": {"$sum": {"$cond": [{"$eq": ["$status", REVIEW]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$eq": ["$status", FAILED]}, 1, 0]}},
                "rejected": {"$sum": {"$cond": [{"$eq": ["$status", REJECTED]}, 1, 0]}},
                "confidence": {"$avg": "$confidence_score"},
                "time_ms": {"$avg": "$total_processing_time_ms"},
            }},
        ]))
        t = rows[0] if rows else {"runs": 0, "completed": 0, "review": 0, "failed": 0, "rejected": 0,
                                  "confidence": None, "time_ms": None}
        conf = t.get("confidence")
        t["confidence"] = round(conf * 100 if conf <= 1 else conf, 1) if conf is not None else None
        t["time_s"] = round(t["time_ms"] / 1000, 1) if t.get("time_ms") is not None else None
        t["completion"] = _pct(t["completed"], t["runs"])
        return t

    def _submissions(self, start: dt.datetime | None, end: dt.datetime | None) -> int:
        """Submissions received in the window. With a process filter: distinct submissions it ran on."""
        if self.scope.process:
            fks = [SOURCES[self.scope.source]["run_fk"]] if self.scope.source else [c["run_fk"] for c in SOURCES.values()]
            submission: Any = f"${fks[-1]}"
            for fk in reversed(fks[:-1]):  # the run's email id, else webhook id, else manual-upload id
                submission = {"$ifNull": [f"${fk}", submission]}
            rows = list(self.db.extraction_results.aggregate([
                {"$match": self.scope.runs(start, end)},
                {"$project": {"s": submission}},
                {"$match": {"s": {"$ne": None}}},
                {"$group": {"_id": "$s"}},
                {"$count": "n"},
            ]))
            return rows[0]["n"] if rows else 0
        n = 0
        for src, cfg in SOURCES.items():
            if self.scope.source and src != self.scope.source:
                continue
            flt = {cfg["received"]: {k: v for k, v in (("$gte", start), ("$lt", end)) if v}} if start or end else {}
            n += self.db[cfg["collection"]].count_documents(flt)
        return n

    def _first_day(self) -> dt.date:
        """Where the daily axis starts: the period start, or the first run in scope for 'all time'."""
        if self.scope.start:
            return self.scope.start.date()
        first = list(self.db.extraction_results.find(self.scope.runs(), {"created_at": 1})
                     .sort("created_at", 1).limit(1))
        return first[0]["created_at"].astimezone(IST).date() if first else dt.datetime.now(IST).date()

    def _days_axis(self) -> list[str]:
        start, today = self._first_day(), dt.datetime.now(IST).date()
        n = min((today - start).days, MAX_DAILY_POINTS - 1)
        return [(today - dt.timedelta(days=n - i)).isoformat() for i in range(n + 1)]

    def _daily_runs(self, axis: list[str]) -> dict[str, dict[str, float]]:
        """Per IST day: runs, completed, review, failed, rejected, confidence, time_s."""
        since = _ist_midnight(dt.date.fromisoformat(axis[0]))
        out: dict[str, dict[str, float]] = {d: {} for d in axis}
        for r in self.db.extraction_results.aggregate([
            {"$match": self.scope.runs(since)},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at", "timezone": IST_OFFSET}},
                "runs": {"$sum": 1},
                "completed": {"$sum": {"$cond": [{"$eq": ["$status", DONE]}, 1, 0]}},
                "review": {"$sum": {"$cond": [{"$eq": ["$status", REVIEW]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$eq": ["$status", FAILED]}, 1, 0]}},
                "rejected": {"$sum": {"$cond": [{"$eq": ["$status", REJECTED]}, 1, 0]}},
                "confidence": {"$avg": "$confidence_score"},
                "time_ms": {"$avg": "$total_processing_time_ms"},
            }},
        ]):
            if r["_id"] in out:
                out[r["_id"]] = r
        return out

    def _daily_submissions(self, axis: list[str]) -> list[int]:
        since = _ist_midnight(dt.date.fromisoformat(axis[0]))
        counts = {d: 0 for d in axis}
        for src, cfg in SOURCES.items():
            if self.scope.source and src != self.scope.source:
                continue
            for r in self.db[cfg["collection"]].aggregate([
                {"$match": {cfg["received"]: {"$gte": since}}},
                {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": f"${cfg['received']}",
                                                      "timezone": IST_OFFSET}}, "n": {"$sum": 1}}},
            ]):
                if r["_id"] in counts:
                    counts[r["_id"]] += r["n"]
        return [counts[d] for d in axis]

    def _process_names(self) -> dict[Any, str]:
        return {p["_id"]: p.get("name") or "Unnamed process" for p in self.db.processes.find({}, {"name": 1})}

    # --- panels --------------------------------------------------------------------------------
    def kpis(self) -> list[dict[str, Any]]:
        s = self.scope
        cur, prev = self._run_totals(s.runs(s.start)), (self._run_totals(s.runs(s.prev_start, s.start))
                                                         if s.start else None)
        subs = self._submissions(s.start, None)
        prev_subs = self._submissions(s.prev_start, s.start) if s.start else None
        backlog = self.db.extraction_results.count_documents({**s.runs(), "status": REVIEW})
        oldest = list(self.db.extraction_results.find({**s.runs(), "status": REVIEW}, {"created_at": 1})
                      .sort("created_at", 1).limit(1))
        wait_days = ((dt.datetime.now(dt.timezone.utc) - oldest[0]["created_at"]).days if oldest else None)

        axis = self._days_axis()
        daily = self._daily_runs(axis)
        spark = lambda key: [daily[d].get(key, 0) or 0 for d in axis]  # noqa: E731
        rate = [_pct(daily[d].get("completed", 0), daily[d].get("runs", 0)) for d in axis]
        conf = [round(v * 100 if v <= 1 else v, 1) if (v := daily[d].get("confidence")) is not None else None
                for d in axis]
        secs = [round(v / 1000, 1) if (v := daily[d].get("time_ms")) is not None else None for d in axis]

        def kpi(key, title, value, previous, better, kind="count", unit="", sp=None, hint=None):
            return {"key": key, "title": title, "value": value, "unit": unit, "previous": previous,
                    "delta": _delta(value, previous, kind), "delta_kind": kind, "better": better,
                    "spark": sp, "hint": hint}

        p = prev or {}
        return [
            kpi("submissions", "Submissions", subs, prev_subs, "neutral", sp=self._daily_submissions(axis)),
            kpi("runs", "Extraction runs", cur["runs"], p.get("runs"), "neutral", sp=spark("runs")),
            kpi("completion", "Completion rate", cur["completion"], p.get("completion"), "higher", "points", "%",
                rate, "Runs completed ÷ runs started"),
            kpi("failed", "Failed runs", cur["failed"], p.get("failed"), "lower", sp=spark("failed")),
            kpi("review", "Awaiting review", backlog, None, "lower", sp=spark("review"),
                hint=f"Oldest has waited {wait_days} days" if wait_days is not None else "Nothing waiting"),
            kpi("confidence", "Avg confidence", cur["confidence"], p.get("confidence"), "higher", "points", "%",
                conf),
            kpi("time", "Avg processing time", cur["time_s"], p.get("time_s"), "lower", "count", "s", secs),
        ]

    def pipeline(self) -> dict[str, Any]:
        """Documents received in the period, followed to the furthest point any of their runs reached.

        Only original documents count: pages split from a file (metadata.parent_file_id) and documents
        fetched by a workflow's API connector (metadata.parent_ref_id) are outputs, not arrivals.
        Two plain reads joined here - a $lookup from files to extraction_results runs past a minute on
        Cosmos DB."""
        s = self.scope
        links = [cfg["file_fk"] for src, cfg in SOURCES.items() if not s.source or src == s.source]
        match: dict[str, Any] = {
            "$or": [{fk: {"$exists": True, "$ne": None}} for fk in links],
            "metadata.parent_file_id": {"$in": [None]},
            "metadata.parent_ref_id": {"$in": [None]},
        }
        if s.start:
            match["uploaded_at"] = {"$gte": s.start}
        statuses_of: dict[Any, list[str]] = {}
        for r in self.db.extraction_results.find(s.runs(), {"file_id": 1, "status": 1}):
            statuses_of.setdefault(r.get("file_id"), []).append(r.get("status"))
        received = processed = extracted = completed = review = failed = rejected = 0
        for f in self.db.files.find(match, {"_id": 1}):
            statuses = statuses_of.get(f["_id"], [])
            if s.process and not statuses:
                continue  # a process only sees the documents it ran on
            received += 1
            if not statuses:
                continue
            processed += 1
            if DONE in statuses:
                extracted += 1
                completed += 1
            elif REVIEW in statuses:
                extracted += 1
                review += 1
            elif REJECTED in statuses:
                extracted += 1
                rejected += 1
            else:
                failed += 1
        stages = [
            {"key": "received", "label": "Received", "value": received, "hint": "Documents uploaded in the period"},
            {"key": "processed", "label": "Processed", "value": processed, "hint": "Went through at least one process"},
            {"key": "extracted", "label": "Extracted", "value": extracted, "hint": "At least one run finished extraction"},
            {"key": "completed", "label": "Completed", "value": completed, "hint": "At least one run completed"},
        ]
        leaks = [
            {"key": "unprocessed", "label": "Never processed", "value": received - processed, "tone": "neutral"},
            {"key": "failed", "label": "Failed in processing", "value": failed, "tone": "critical"},
            {"key": "review", "label": "Waiting for review", "value": review, "tone": "warning"},
            {"key": "rejected", "label": "Rejected in review", "value": rejected, "tone": "critical"},
        ]
        if s.process:
            leaks = leaks[1:]  # a process only sees files it ran on
        return {"stages": stages, "leaks": leaks,
                "note": "Counts original documents only - split pages and documents fetched by connectors "
                        "are outputs of a run, not arrivals."}

    def processes(self) -> list[dict[str, Any]]:
        """Scorecard per process. Ignores the process filter (it is how you pick one)."""
        s = self.scope
        match = {k: v for k, v in s.runs(s.start).items() if k != "proccess_id"}
        names = self._process_names()
        axis = self._days_axis()
        since = _ist_midnight(dt.date.fromisoformat(axis[0]))
        trend: dict[Any, dict[str, int]] = {}
        for r in self.db.extraction_results.aggregate([
            {"$match": {**match, "created_at": {"$gte": since}}},
            {"$group": {"_id": {"p": "$proccess_id", "d": {"$dateToString": {
                "format": "%Y-%m-%d", "date": "$created_at", "timezone": IST_OFFSET}}}, "n": {"$sum": 1}}},
        ]):
            trend.setdefault(r["_id"]["p"], {})[r["_id"]["d"]] = r["n"]
        rows = []
        for r in self.db.extraction_results.aggregate([
            {"$match": match},
            {"$group": {
                "_id": "$proccess_id",
                "runs": {"$sum": 1},
                "completed": {"$sum": {"$cond": [{"$eq": ["$status", DONE]}, 1, 0]}},
                "review": {"$sum": {"$cond": [{"$eq": ["$status", REVIEW]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$eq": ["$status", FAILED]}, 1, 0]}},
                "rejected": {"$sum": {"$cond": [{"$eq": ["$status", REJECTED]}, 1, 0]}},
                "confidence": {"$avg": "$confidence_score"},
                "time_ms": {"$avg": "$total_processing_time_ms"},
                "last_run": {"$max": "$created_at"},
            }},
            {"$sort": {"runs": -1}},
        ]):
            conf = r.get("confidence")
            rows.append({
                "process_id": str(r["_id"]) if r["_id"] is not None else None,
                "name": names.get(r["_id"], "Deleted process"),
                "runs": r["runs"], "completed": r["completed"], "review": r["review"],
                "failed": r["failed"], "rejected": r["rejected"],
                "completion": _pct(r["completed"], r["runs"]),
                "confidence": round(conf * 100 if conf <= 1 else conf, 1) if conf is not None else None,
                "time_s": round(r["time_ms"] / 1000, 1) if r.get("time_ms") is not None else None,
                "last_run": r["last_run"].isoformat() if r.get("last_run") else None,
                "spark": [trend.get(r["_id"], {}).get(d, 0) for d in axis],
            })
        return rows

    def submission_completion(self) -> dict[Any, tuple[int, int]]:
        """Per process: (submissions it ran on, submissions with at least one completed run of it)."""
        s = self.scope
        fks = [SOURCES[s.source]["run_fk"]] if s.source else [c["run_fk"] for c in SOURCES.values()]
        submission: Any = f"${fks[-1]}"
        for fk in reversed(fks[:-1]):  # the run's email id, else webhook id, else manual-upload id
            submission = {"$ifNull": [f"${fk}", submission]}
        out: dict[Any, tuple[int, int]] = {}
        for r in self.db.extraction_results.aggregate([
            {"$match": s.runs(s.start)},
            {"$project": {"p": "$proccess_id", "s": submission,
                          "done": {"$cond": [{"$eq": ["$status", DONE]}, 1, 0]}}},
            {"$match": {"s": {"$ne": None}}},
            {"$group": {"_id": {"p": "$p", "s": "$s"}, "done": {"$max": "$done"}}},
            {"$group": {"_id": "$_id.p", "subs": {"$sum": 1}, "done": {"$sum": "$done"}}},
        ]):
            out[r["_id"]] = (r["subs"], r["done"])
        return out

    def trend(self) -> dict[str, Any]:
        axis = self._days_axis()
        daily = self._daily_runs(axis)
        series = [{"name": name, "data": [daily[d].get(key, 0) or 0 for d in axis]}
                  for key, name in (("completed", "Completed"), ("review", "Awaiting review"),
                                    ("failed", "Failed"), ("rejected", "Rejected"))]
        series = [x for x in series if any(x["data"])] or series[:1]
        return {"title": "Runs per day by outcome", "type": "line", "labels": axis, "series": series,
                "status_colors": True}

    def bottlenecks(self) -> list[dict[str, Any]]:
        """Workflow steps where runs stopped: failed, awaiting approval or rejected (file_process_tracker)."""
        s = self.scope
        match: dict[str, Any] = {"status": {"$in": STUCK_STEP}}
        if s.start:
            match["createdAt"] = {"$gte": s.start}
        if s.source:
            match[SOURCES[s.source]["run_fk"]] = {"$exists": True, "$ne": None}
        if s.process:
            match["process_id"] = s.process  # spelt correctly in this collection
        labels: dict[tuple[Any, str], str] = {}
        names = {}
        for p in self.db.processes.find({}, {"name": 1, "workflow.nodes.id": 1, "workflow.nodes.label": 1}):
            names[p["_id"]] = p.get("name") or "Unnamed process"
            for n in (p.get("workflow") or {}).get("nodes", []):
                labels[(p["_id"], n.get("id"))] = n.get("label") or n.get("id")
        steps: dict[tuple[str, str], dict[str, Any]] = {}
        for r in self.db.file_process_tracker.aggregate([
            {"$match": match},
            {"$group": {"_id": {"p": "$process_id", "n": "$node_id", "s": "$status"}, "c": {"$sum": 1}}},
        ]):
            pid, node, status = r["_id"].get("p"), r["_id"].get("n"), r["_id"].get("s")
            process = names.get(pid, "Deleted process")
            step = labels.get((pid, node), "Step removed from workflow")
            row = steps.setdefault((process, step), {"process": process, "step": step, "process_id": str(pid),
                                                     "failed": 0, "awaiting_approval": 0, "rejected": 0})
            row[status] = row.get(status, 0) + r["c"]
        out = sorted(steps.values(), key=lambda x: -(x["failed"] + x["awaiting_approval"] + x["rejected"]))
        for row in out:
            row["total"] = row["failed"] + row["awaiting_approval"] + row["rejected"]
        return out[:8]

    def review_queue(self) -> list[dict[str, Any]]:
        s = self.scope
        names = self._process_names()
        now = dt.datetime.now(dt.timezone.utc)
        rows = []
        for r in self.db.extraction_results.aggregate([
            {"$match": {**s.runs(), "status": REVIEW}},
            {"$sort": {"created_at": 1}},
            {"$limit": 8},
            {"$lookup": {"from": "files", "localField": "file_id", "foreignField": "_id", "as": "f"}},
            {"$project": {"created_at": 1, "proccess_id": 1, "confidence_score": 1,
                          "file": {"$ifNull": [{"$first": "$f.original_filename"}, {"$first": "$f.filename"}]}}},
        ]):
            conf = r.get("confidence_score")
            rows.append({
                "run_id": str(r["_id"]),
                "file": r.get("file") or "Unknown file",
                "process": names.get(r.get("proccess_id"), "Deleted process"),
                "waiting_since": r["created_at"].isoformat() if r.get("created_at") else None,
                "waiting_days": (now - r["created_at"]).days if r.get("created_at") else None,
                "confidence": round(conf * 100 if conf <= 1 else conf, 1) if conf is not None else None,
            })
        return rows

    def by_source(self) -> dict[str, Any]:
        s = self.scope
        if s.process:  # the process's runs, by where their documents came from
            rows = [{"source": SOURCE_LABELS[src], "n": self.db.extraction_results.count_documents(
                {**s.runs(s.start), cfg["run_fk"]: {"$exists": True, "$ne": None}})}
                for src, cfg in SOURCES.items() if not s.source or src == s.source]
            return from_rows("Runs by source", "doughnut", rows, "source", ["n"], ["Runs"])
        rows = [{"source": SOURCE_LABELS[src], "n": self.db[cfg["collection"]].count_documents(
            {cfg["received"]: {"$gte": s.start}} if s.start else {})}
            for src, cfg in SOURCES.items() if not s.source or src == s.source]
        return from_rows("Submissions by source", "doughnut", rows, "source", ["n"], ["Submissions"])

    def recent(self) -> dict[str, Any]:
        rows = IdpFlow(self.db).find_submissions(source=self.scope.source, days=self.scope.days, limit=8)
        cols = ["received_at", "source", "title", "status", "files", "runs", "run_status"]
        return {"title": "Latest submissions", "type": "table", "columns": cols,
                "rows": [[r.get(c) for c in cols] for r in rows],
                "row_ids": [r.get("submission_id") for r in rows]}

    def insights(self, out: dict[str, Any]) -> list[dict[str, str]]:
        """Plain sentences, each built around figures computed above (observation / risk / gap)."""
        notes: list[dict[str, str]] = []
        procs = [p for p in out.get("processes") or [] if p["runs"] >= 3]
        kpis = {k["key"]: k for k in out.get("kpis") or []}
        runs = kpis.get("runs", {}).get("value") or 0
        period = f"the last {self.scope.days} days" if self.scope.days else "all time"

        if not runs:
            last = out.get("latest_activity")
            notes.append({"kind": "gap", "text": f"No extraction runs in {period}" + (
                f" - the most recent was on {dt.datetime.fromisoformat(last).astimezone(IST):%d %b %Y}. "
                "Widen the period to see it." if last else ".")})
            return notes
        if procs and not self.scope.process:
            busiest = procs[0]
            notes.append({"kind": "observation", "text": f"{busiest['name']} handles {_pct(busiest['runs'], runs):g}% "
                          f"of all runs ({busiest['runs']} of {runs})."})
            weakest = min(procs, key=lambda p: p["completion"] if p["completion"] is not None else 101)
            if weakest["completion"] is not None and weakest["completion"] < 60:
                notes.append({"kind": "risk", "text": f"{weakest['name']} completes only {weakest['completion']:g}% "
                              f"of its runs - {weakest['failed']} failed and {weakest['review']} are awaiting review."})
        if self.scope.process:
            done = kpis.get("completion", {}).get("value")
            name = out.get("process_name") or "This process"
            if done is not None:
                kind = "risk" if done < 60 else "observation"
                notes.append({"kind": kind, "text": f"{name} completed {done:g}% of its {runs} runs in {period}."})
        review = kpis.get("review", {})
        if review.get("value"):
            notes.append({"kind": "risk", "text": f"{review['value']} runs are waiting for review. "
                          f"{review.get('hint') or ''}".strip()})
        stuck = (out.get("bottlenecks") or [None])[0]
        if stuck and stuck["total"]:
            what = "wait for approval" if stuck["awaiting_approval"] >= stuck["failed"] else "fail"
            notes.append({"kind": "risk", "text": f"Most stopped runs {what} at the “{stuck['step']}” step of "
                          f"{stuck['process']} ({stuck['total']} runs)."})
        delta = kpis.get("runs", {}).get("delta")
        if delta is not None and abs(delta) >= 0.1:
            notes.append({"kind": "observation", "text": f"Runs are {'up' if delta > 0 else 'down'} "
                          f"{abs(delta) * 100:.0f}% on the previous {self.scope.days} days."})
        conf = kpis.get("confidence", {})
        if conf.get("value") is not None and conf["value"] < 80:
            notes.append({"kind": "observation", "text": f"Average extraction confidence is {conf['value']:g}% - "
                          "below the 80% most teams treat as reliable."})
        return notes[:5]

    # --- everything ----------------------------------------------------------------------------
    def build(self, days: int = 30, source: str = "", process: str = "") -> dict[str, Any]:
        self.scope = Scope(days, source, process)
        names = self._process_names()
        run_counts = {r["_id"]: r["n"] for r in self.db.extraction_results.aggregate(
            [{"$group": {"_id": "$proccess_id", "n": {"$sum": 1}}}])}
        last = list(self.db.extraction_results.find(self.scope.runs(), {"created_at": 1})
                    .sort("created_at", -1).limit(1))
        out: dict[str, Any] = {
            "days": self.scope.days, "source": source, "process": process,
            "process_name": names.get(self.scope.process) if self.scope.process else None,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "latest_activity": last[0]["created_at"].isoformat() if last else None,
            "filters": {
                "sources": [{"value": k, "label": v} for k, v in SOURCE_LABELS.items()],
                "processes": sorted(({"value": str(pid), "label": name, "runs": run_counts.get(pid, 0)}
                                     for pid, name in names.items()), key=lambda p: (-p["runs"], p["label"])),
            },
            "errors": {},
        }
        panels: list[tuple[str, Callable[[], Any]]] = [
            ("kpis", self.kpis), ("pipeline", self.pipeline), ("processes", self.processes),
            ("trend", self.trend), ("bottlenecks", self.bottlenecks), ("review_queue", self.review_queue),
            ("by_source", self.by_source), ("recent", self.recent),
        ]
        def run(item: tuple[str, Callable[[], Any]]) -> tuple[str, Any, str | None]:
            key, fn = item
            try:
                return key, fn(), None
            except Exception as ex:
                return key, None, f"{type(ex).__name__}: {ex}"

        # Panels are independent reads, so they run side by side (pymongo is thread-safe). Kept to a few
        # threads: each new Cosmos DB connection takes seconds to log in.
        with ThreadPoolExecutor(max_workers=PANEL_WORKERS) as pool:
            for key, value, error in pool.map(run, panels):
                out[key] = value
                if error:
                    out["errors"][key] = error
        out["insights"] = self.insights(out)
        return out


def process_performance(db, days: int = 0, source: str = "", process: str = "") -> dict[str, Any]:
    """Completion per process (runs and submissions) and the workflow steps where runs stop, with step
    names resolved from each process's workflow - for the chatbot (MCP tool idp_process_performance).
    Returns the rows plus ready-made charts: a table per process and a ranking of stuck steps."""
    d = Dashboard(db)
    d.scope = Scope(days, source, process)
    subs = d.submission_completion()
    oid = {str(k): k for k in subs}
    rows = []
    for p in d.processes():
        if d.scope.process and p["process_id"] != str(d.scope.process):
            continue
        n, done = subs.get(oid.get(p["process_id"]), (0, 0))
        rows.append({
            "process": p["name"], "process_id": p["process_id"],
            "submissions": n, "submissions_completed": done, "submission_completion_pct": _pct(done, n),
            "runs": p["runs"], "runs_completed": p["completed"], "run_completion_pct": p["completion"],
            "awaiting_review": p["review"], "failed": p["failed"], "rejected": p["rejected"],
            "avg_confidence_pct": p["confidence"], "avg_time_s": p["time_s"], "last_run": p["last_run"],
        })
    steps = d.bottlenecks()
    period = f"last {d.scope.days} days" if d.scope.days else "all time"
    cols = ["process", "submissions", "submissions_completed", "submission_completion_pct", "runs",
            "runs_completed", "run_completion_pct", "awaiting_review", "failed", "rejected"]
    charts: list[dict[str, Any]] = [{
        "title": f"Completion by process ({period})", "type": "table",
        "columns": ["Process", "Submissions", "Submissions completed", "Submission completion %", "Runs",
                    "Runs completed", "Run completion %", "Awaiting review", "Failed", "Rejected"],
        "rows": [[r[c] for c in cols] for r in rows],
    }]
    if steps:
        charts.append({
            "title": f"Where runs stop - workflow steps ({period})", "type": "hbar",
            "labels": [f"{s['step']} ({s['process']})" for s in steps],
            "series": [{"name": n, "data": [s[k] for s in steps]} for k, n in
                       (("failed", "Failed"), ("awaiting_approval", "Awaiting approval"), ("rejected", "Rejected"))
                       if any(s[k] for s in steps)],
            "status_colors": True,
        })
    return {"period": period, "processes": rows, "stuck_steps": steps, "charts": charts,
            "definitions": {
                "submission_completion_pct": "submissions with at least one completed run of the process / "
                                             "submissions the process ran on",
                "run_completion_pct": "completed runs / all runs of the process",
                "stuck_steps": "file_process_tracker steps with status failed, awaiting_approval or rejected, "
                               "named from processes.workflow.nodes[].label",
            }}
