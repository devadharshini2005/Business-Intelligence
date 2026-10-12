"""Dashboard analytics for the Actuvara IDP database - read-only.

Every query here is a fixed find / aggregate pipeline built in this module
(no user-supplied operators), used by api_server.py to feed the BI dashboard.

Time windows use the creation time embedded in each document's ObjectId
(`_id`), so they work the same for every collection, use the `_id` index and
don't depend on how a collection names or types its date fields. `days <= 0`
means all time (no window).
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from bson import ObjectId

from idp_flow import ATTENTION, SOURCES, IdpFlow

SOURCE_COLLECTIONS = {src: cfg["collection"] for src, cfg in SOURCES.items()}
SOURCE_NAMES = {"email": "Email", "webhook": "Webhook", "manual_upload": "Manual upload"}
TREND_SCAN_CAP = 50_000  # max ids read per collection when $toDate isn't supported
MAX_DAYS = 36_500  # longer windows are treated as all time


def _window(days: int, now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime, dt.datetime]:
    """(previous period start, current period start, now) for a `days`-long window."""
    now = now or dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=days)
    return start - dt.timedelta(days=days), start, now


def _start(days: int) -> dt.datetime | None:
    """Start of the current `days`-long window, or None for all time."""
    return _window(days)[1] if 0 < days <= MAX_DAYS else None


def _id_range(start: dt.datetime | None, end: dt.datetime | None = None) -> dict[str, Any]:
    rng: dict[str, Any] = {}
    if start is not None:
        rng["$gte"] = ObjectId.from_datetime(start)
    if end is not None:
        rng["$lt"] = ObjectId.from_datetime(end)
    return {"_id": rng} if rng else {}


def _pct_change(cur: float | None, prev: float | None) -> float | None:
    if cur is None or not prev:
        return None
    return round(100 * (cur - prev) / prev, 1)


class BiAnalytics:
    """Aggregates for the dashboard: KPIs, file funnel, trend, processes, node hotspots."""

    def __init__(self, db) -> None:
        self.db = db

    # --- KPIs ----------------------------------------------------------------
    def _period(self, start: dt.datetime | None, end: dt.datetime | None) -> dict[str, Any]:
        rng = _id_range(start, end)
        by_source = {src: self.db[coll].count_documents(rng) for src, coll in SOURCE_COLLECTIONS.items()}
        files = self.db.files.count_documents({**rng, "metadata.parent_ref_id": {"$exists": False}})
        runs = list(self.db.extraction_results.aggregate([
            {"$match": rng},
            {"$group": {"_id": "$status", "n": {"$sum": 1},
                        "validated": {"$sum": {"$cond": [{"$eq": ["$is_validated", True]}, 1, 0]}},
                        "ms": {"$avg": "$total_processing_time_ms"},
                        "conf": {"$avg": "$confidence_score"}}},
        ]))
        status = {(r["_id"] or "unknown"): r["n"] for r in runs}
        total_runs = sum(status.values())
        completed = status.get("completed", 0)
        failed = sum(n for s, n in status.items() if s in ("failed", "rejected", "error"))

        def wavg(key: str) -> float | None:
            pairs = [(r[key], r["n"]) for r in runs if isinstance(r.get(key), (int, float))]
            weight = sum(n for _, n in pairs)
            return sum(v * n for v, n in pairs) / weight if weight else None

        avg_ms = wavg("ms")
        conf = wavg("conf")
        return {
            "submissions": sum(by_source.values()),
            "submissions_by_source": by_source,
            "files": files,
            "runs": total_runs,
            "runs_by_status": dict(sorted(status.items(), key=lambda kv: -kv[1])),
            "completed_runs": completed,
            "failed_runs": failed,
            "validated_runs": sum(r["validated"] for r in runs),
            "success_rate": round(100 * completed / total_runs, 1) if total_runs else None,
            "avg_processing_s": round(avg_ms / 1000, 1) if avg_ms is not None else None,
            "avg_confidence": round(conf, 3) if conf is not None else None,
        }

    def _file_funnel(self, start: dt.datetime | None, files_received: int) -> list[dict[str, Any]]:
        """Files received in the window and how far they got. Every stage counts files, so
        each stage is a subset of the one before (a file can have several runs)."""
        file_ids = {"$gte": ObjectId.from_datetime(start)} if start is not None else {"$ne": None}
        rows = list(self.db.extraction_results.aggregate([
            {"$match": {"file_id": file_ids}},  # runs of files created in the window
            {"$group": {"_id": "$file_id",
                        "completed": {"$max": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
                        "validated": {"$max": {"$cond": [{"$and": [{"$eq": ["$status", "completed"]},
                                                                    {"$eq": ["$is_validated", True]}]}, 1, 0]}}}},
            {"$group": {"_id": None, "processed": {"$sum": 1}, "completed": {"$sum": "$completed"},
                        "validated": {"$sum": "$validated"}}},
        ]))
        agg = rows[0] if rows else {"processed": 0, "completed": 0, "validated": 0}
        received = max(files_received, agg["processed"])
        return [
            {"stage": "Files received", "value": received},
            {"stage": "Processed", "value": agg["processed"]},
            {"stage": "Completed", "value": agg["completed"]},
            {"stage": "Validated", "value": agg["validated"]},
        ]

    def overview(self, days: int = 30) -> dict[str, Any]:
        if _start(days) is None:  # all time: there is no previous period to compare with
            cur = self._period(None, None)
            return {"days": 0, "from": None, "to": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "previous_from": None, "current": cur, "previous": None,
                    "change_pct": {k: None for k in ("submissions", "files", "runs", "completed_runs", "failed_runs",
                                                     "success_rate", "avg_processing_s", "avg_confidence")},
                    "funnel": self._file_funnel(None, cur["files"])}
        prev_start, start, now = _window(days)
        cur = self._period(start, None)
        prev = self._period(prev_start, start)
        change = {k: _pct_change(cur[k], prev[k])
                  for k in ("submissions", "files", "runs", "completed_runs", "failed_runs",
                            "success_rate", "avg_processing_s", "avg_confidence")}
        return {"days": days, "from": start.isoformat(), "to": now.isoformat(),
                "previous_from": prev_start.isoformat(),
                "current": cur, "previous": prev, "change_pct": change,
                "funnel": self._file_funnel(start, cur["files"])}

    # --- daily trend ----------------------------------------------------------
    def _daily_counts(self, collection: str, start: dt.datetime) -> dict[str, int]:
        try:
            rows = self.db[collection].aggregate([
                {"$match": _id_range(start)},
                {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$toDate": "$_id"}}},
                            "n": {"$sum": 1}}},
            ])
            return {r["_id"]: r["n"] for r in rows}
        except Exception:
            # Some servers lack $toDate on ObjectId - bucket the ids here instead.
            out: dict[str, int] = {}
            for d in self.db[collection].find(_id_range(start), {"_id": 1}, limit=TREND_SCAN_CAP):
                day = d["_id"].generation_time.strftime("%Y-%m-%d")
                out[day] = out.get(day, 0) + 1
            return out

    def _first_created(self) -> dt.datetime | None:
        """Creation time of the oldest submission or run, from its ObjectId."""
        times = []
        for coll in [*SOURCE_COLLECTIONS.values(), "extraction_results"]:
            doc = self.db[coll].find_one({"_id": {"$type": "objectId"}}, {"_id": 1}, sort=[("_id", 1)])
            if doc:
                times.append(doc["_id"].generation_time)
        return min(times, default=None)

    def trend(self, days: int = 30) -> dict[str, Any]:
        _, start, now = _window(days)
        if _start(days) is None:  # all time: start at the first day with data
            start = self._first_created() or now
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        series = {src: self._daily_counts(coll, start) for src, coll in SOURCE_COLLECTIONS.items()}
        runs = self._daily_counts("extraction_results", start)
        rows = []
        day = start
        while day.date() <= now.date():
            key = day.strftime("%Y-%m-%d")
            rows.append({"date": key, **{src: series[src].get(key, 0) for src in series},
                         "runs": runs.get(key, 0)})
            day += dt.timedelta(days=1)
        peak = max(rows, key=lambda r: sum(r[s] for s in series), default=None)
        return {"days": days if _start(days) else 0, "sources": list(series), "rows": rows,
                "peak": peak["date"] if peak and any(peak[s] for s in series) else None}

    # --- processes ------------------------------------------------------------
    def processes(self, days: int = 30, limit: int = 12) -> list[dict[str, Any]]:
        start = _start(days)
        rows = list(self.db.extraction_results.aggregate([
            {"$match": _id_range(start)},
            {"$group": {"_id": {"p": "$proccess_id", "s": "$status"}, "n": {"$sum": 1},
                        "ms": {"$avg": "$total_processing_time_ms"}}},
        ]))
        procs: dict[Any, dict[str, Any]] = {}
        for r in rows:
            pid = r["_id"].get("p")
            p = procs.setdefault(pid, {"process_id": str(pid) if pid else None, "runs": 0,
                                       "by_status": {}, "_ms": 0.0, "_msn": 0})
            p["runs"] += r["n"]
            p["by_status"][r["_id"].get("s") or "unknown"] = r["n"]
            if isinstance(r.get("ms"), (int, float)):
                p["_ms"] += r["ms"] * r["n"]
                p["_msn"] += r["n"]
        names = {str(d["_id"]): d.get("name") for d in self.db.processes.find(
            {"_id": {"$in": [p for p in procs if isinstance(p, ObjectId)]}}, {"name": 1})}
        out = []
        for p in sorted(procs.values(), key=lambda x: -x["runs"])[:limit]:
            completed = p["by_status"].get("completed", 0)
            failed = sum(n for s, n in p["by_status"].items() if s in ("failed", "rejected", "error"))
            out.append({
                "process_id": p["process_id"],
                "name": names.get(p["process_id"] or "") or "(no process)",
                "runs": p["runs"],
                "completed": completed,
                "failed": failed,
                "other": p["runs"] - completed - failed,
                "success_rate": round(100 * completed / p["runs"], 1) if p["runs"] else None,
                "avg_processing_s": round(p["_ms"] / p["_msn"] / 1000, 1) if p["_msn"] else None,
            })
        return out

    # --- node hotspots --------------------------------------------------------
    def node_hotspots(self, days: int = 30, limit: int = 10) -> list[dict[str, Any]]:
        """Workflow nodes that most often fail, get rejected or wait for approval."""
        start = _start(days)
        rows = list(self.db.file_process_tracker.aggregate([
            {"$match": {**_id_range(start), "status": {"$in": sorted(ATTENTION)}}},
            {"$group": {"_id": {"node": "$node_id", "s": "$status"}, "n": {"$sum": 1},
                        "sub_type": {"$first": "$node_data.node_sub_type"},
                        "run": {"$first": "$extraction_result_id"},
                        "reason": {"$first": "$error_details.reason"}}},
            {"$sort": {"n": -1}},
            {"$limit": 200},
        ]))
        if not rows:
            return []
        # Label each node from its workflow definition (via one sample run's process).
        run_proc = {r["_id"]: r.get("proccess_id") for r in self.db.extraction_results.find(
            {"_id": {"$in": [r["run"] for r in rows if r.get("run")]}}, {"proccess_id": 1})}
        procs = IdpFlow(self.db)._process_maps([p for p in run_proc.values() if p])
        nodes: dict[Any, dict[str, Any]] = {}
        for r in rows:
            nid = r["_id"].get("node")
            proc = procs.get(str(run_proc.get(r.get("run"))))
            label = ((proc or {}).get("nodes") or {}).get(nid, {}).get("label")
            n = nodes.setdefault(nid, {"node_id": nid, "name": label or r.get("sub_type") or nid,
                                       "process": (proc or {}).get("name"), "total": 0,
                                       "by_status": {}, "sample_reason": None, "sample_run_id": None})
            n["total"] += r["n"]
            n["by_status"][r["_id"].get("s")] = r["n"]
            n["sample_reason"] = n["sample_reason"] or (str(r["reason"])[:240] if r.get("reason") else None)
            n["sample_run_id"] = n["sample_run_id"] or (str(r["run"]) if r.get("run") else None)
        return sorted(nodes.values(), key=lambda x: -x["total"])[:limit]

    # --- collections ----------------------------------------------------------
    def collections(self) -> list[dict[str, Any]]:
        def count(name: str) -> dict[str, Any]:
            try:
                # Not estimated_document_count: on Cosmos DB vCore the count/collStats commands it relies on
                # take 15-30 s per collection, while count_documents (an aggregation) returns in milliseconds.
                n = self.db[name].count_documents({}, maxTimeMS=5000)
            except Exception:
                n = None
            return {"collection": name, "documents": n}

        names = sorted(self.db.list_collection_names(), key=str.lower)
        with ThreadPoolExecutor(max_workers=16) as pool:  # one round trip each; run them side by side
            out = list(pool.map(count, names))
        return sorted(out, key=lambda r: -(r["documents"] or 0))


def metric_rows(bi: BiAnalytics, metric: str, days: int) -> tuple[
    list[dict[str, Any]], str, list[str], list[str], str
]:
    """Return chart rows and labels for a fixed dashboard metric. days <= 0 (or None) means all time."""
    days = int(days or 0)
    days = days if 0 < days <= MAX_DAYS else 0
    period = f"last {days} days" if days else "all time"
    if metric == "runs_by_status":
        statuses = bi.overview(days)["current"]["runs_by_status"]
        rows = [{"status": key, "runs": value} for key, value in statuses.items()]
        return rows, "status", ["runs"], ["Runs"], f"Runs by status ({period})"
    if metric == "submissions_by_source":
        sources = bi.overview(days)["current"]["submissions_by_source"]
        rows = [{"source": SOURCE_NAMES.get(key, key), "submissions": value} for key, value in sources.items()]
        return rows, "source", ["submissions"], ["Submissions"], f"Submissions by source ({period})"
    if metric == "runs_by_process":
        rows = [{"process": process["name"], "runs": process["runs"], "completed": process["completed"],
                 "failed": process["failed"]} for process in bi.processes(days, limit=8)]
        return rows, "process", ["runs"], ["Runs"], f"Runs by process ({period})"
    if metric == "failing_nodes":
        rows = [{"node": f"{node['name']} ({node['process']})" if node.get("process") else node["name"],
                 "count": node["total"], **node["by_status"]} for node in bi.node_hotspots(days, limit=8)]
        return rows, "node", ["count"], ["Failed / rejected / awaiting approval"], \
            f"Workflow nodes needing attention ({period})"
    if metric in ("submissions_per_day", "runs_per_day"):
        trend = bi.trend(days)
        if metric == "runs_per_day":
            rows = [{"date": row["date"], "runs": row["runs"]} for row in trend["rows"]]
            return rows, "date", ["runs"], ["Runs"], f"Runs per day ({period})"
        return (trend["rows"], "date", list(trend["sources"]),
                [SOURCE_NAMES.get(source, source) for source in trend["sources"]],
                f"Submissions per day by source ({period})")
    raise ValueError("metric must be one of runs_by_status, runs_by_process, submissions_by_source, failing_nodes, "
                     "submissions_per_day, runs_per_day")
