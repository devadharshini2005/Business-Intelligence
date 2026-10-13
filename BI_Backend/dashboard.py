"""Analytics dashboard for the IDP (intellidoc) data - read-only.

Every number comes from a fixed aggregation built in this module (no user
input reaches a pipeline except the `days` window). Each widget is computed on
its own, so one failing query shows as an error on that card instead of
breaking the whole dashboard.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from charts import from_rows
from idp_flow import SOURCES, IdpFlow

SOURCE_LABELS = {"email": "Email", "webhook": "Webhook", "manual_upload": "Manual upload"}

# Users are in India; the database stores UTC. Day buckets use IST so "today" means today in India.
IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")
IST_OFFSET = "+05:30"


def _since(days: int) -> dt.datetime | None:
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days) if days > 0 else None


class Dashboard:
    def __init__(self, db) -> None:
        self.db = db

    # --- widgets -------------------------------------------------------------
    def _run_match(self, days: int) -> dict[str, Any]:
        since = _since(days)
        return {"created_at": {"$gte": since}} if since else {}

    def kpis(self, days: int) -> list[dict[str, Any]]:
        since = _since(days)
        submissions = 0
        for cfg in SOURCES.values():
            flt = {cfg["received"]: {"$gte": since}} if since else {}
            submissions += self.db[cfg["collection"]].count_documents(flt)
        files = self.db.files.count_documents({"uploaded_at": {"$gte": since}} if since else {})
        agg = list(self.db.extraction_results.aggregate([
            {"$match": self._run_match(days)},
            {"$group": {
                "_id": None,
                "runs": {"$sum": 1},
                "completed": {"$sum": {"$cond": [{"$in": ["$status", ["completed", "success", "processed"]]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$in": ["$status", ["failed", "error", "rejected"]]}, 1, 0]}},
                "confidence": {"$avg": "$confidence_score"},
                "time_ms": {"$avg": "$total_processing_time_ms"},
            }},
        ]))
        a = agg[0] if agg else {"runs": 0, "completed": 0, "failed": 0, "confidence": None, "time_ms": None}
        rate = round(100 * a["completed"] / a["runs"], 1) if a["runs"] else None
        conf = a.get("confidence")
        if conf is not None and conf <= 1:  # stored as 0-1 -> show as %
            conf *= 100
        return [
            {"title": "Submissions", "type": "kpi", "value": submissions},
            {"title": "Files", "type": "kpi", "value": files},
            {"title": "Extraction runs", "type": "kpi", "value": a["runs"]},
            {"title": "Run success rate", "type": "kpi", "value": rate, "unit": "%"},
            {"title": "Failed runs", "type": "kpi", "value": a["failed"], "status": "critical" if a["failed"] else None},
            {"title": "Avg confidence", "type": "kpi", "value": round(conf, 1) if conf is not None else None, "unit": "%"},
            {"title": "Avg processing time", "type": "kpi",
             "value": round(a["time_ms"] / 1000, 1) if a.get("time_ms") is not None else None, "unit": "s"},
        ]

    def submissions_over_time(self, days: int) -> dict[str, Any]:
        """Per calendar day in India time: dates are stored in UTC, so a submission at 02:00 IST belongs to
        that IST day, not to the previous UTC day."""
        days = days if days > 0 else 90
        start = dt.datetime.now(IST).date() - dt.timedelta(days=days)
        since = dt.datetime.combine(start, dt.time.min, IST)  # IST midnight; pymongo sends it as UTC
        dates = [(start + dt.timedelta(days=i)).isoformat() for i in range(days + 1)]
        series = []
        for src, cfg in SOURCES.items():
            counts = {r["_id"]: r["n"] for r in self.db[cfg["collection"]].aggregate([
                {"$match": {cfg["received"]: {"$gte": since}}},
                {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": f"${cfg['received']}",
                                                      "timezone": IST_OFFSET}},
                            "n": {"$sum": 1}}},
            ])}
            series.append({"name": SOURCE_LABELS[src], "data": [counts.get(d, 0) for d in dates]})
        return {"title": f"Submissions per day (last {days} days)", "type": "line", "labels": dates, "series": series}

    def submissions_by_source(self, days: int) -> dict[str, Any]:
        since = _since(days)
        rows = [{"source": SOURCE_LABELS[src],
                 "n": self.db[cfg["collection"]].count_documents({cfg["received"]: {"$gte": since}} if since else {})}
                for src, cfg in SOURCES.items()]
        return from_rows("Submissions by source", "doughnut", rows, "source", ["n"], ["Submissions"])

    def runs_by_status(self, days: int) -> dict[str, Any]:
        rows = list(self.db.extraction_results.aggregate([
            {"$match": self._run_match(days)},
            {"$group": {"_id": "$status", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
        ]))
        spec = from_rows("Extraction runs by status", "hbar", rows, "_id", ["n"], ["Runs"])
        spec["status_colors"] = True
        return spec

    def top_processes(self, days: int) -> dict[str, Any]:
        rows = list(self.db.extraction_results.aggregate([
            {"$match": self._run_match(days)},
            {"$group": {"_id": "$proccess_id", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": 10},
            {"$lookup": {"from": "processes", "localField": "_id", "foreignField": "_id", "as": "p"}},
            {"$project": {"n": 1, "name": {"$ifNull": [
                {"$first": "$p.name"},
                {"$concat": ["Deleted process (", {"$substrCP": [{"$toString": "$_id"}, 18, 6]}, ")"]}]}}},
        ]))
        return from_rows("Top 10 processes by runs", "hbar", rows, "name", ["n"], ["Runs"])

    def file_types(self, days: int) -> dict[str, Any]:
        since = _since(days)
        rows = list(self.db.files.aggregate([
            {"$match": {"uploaded_at": {"$gte": since}} if since else {}},
            {"$group": {"_id": {"$toLower": {"$ifNull": ["$file_type", "unknown"]}}, "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": 10},
        ]))
        return from_rows("Files by type", "bar", rows, "_id", ["n"], ["Files"])

    def recent_submissions(self, days: int) -> dict[str, Any]:
        rows = IdpFlow(self.db).find_submissions(days=days, limit=10)
        cols = ["received_at", "source", "title", "from", "status", "files", "runs", "run_status"]
        return {"title": "Latest submissions", "type": "table", "columns": cols,
                "rows": [[r.get(c) for c in cols] for r in rows],
                "row_ids": [r.get("submission_id") for r in rows]}

    # --- everything ----------------------------------------------------------
    def build(self, days: int = 30) -> dict[str, Any]:
        widgets: list[tuple[str, Callable[[int], Any]]] = [
            ("over_time", self.submissions_over_time),
            ("by_source", self.submissions_by_source),
            ("runs_by_status", self.runs_by_status),
            ("top_processes", self.top_processes),
            ("file_types", self.file_types),
            ("recent", self.recent_submissions),
        ]
        out: dict[str, Any] = {"days": days, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            out["kpis"] = self.kpis(days)
        except Exception as ex:
            out["kpis"] = []
            out["kpi_error"] = f"{type(ex).__name__}: {ex}"
        charts = []
        for key, fn in widgets:
            try:
                charts.append({"id": key, **fn(days)})
            except Exception as ex:
                charts.append({"id": key, "title": key.replace("_", " ").title(), "type": "error",
                               "error": f"{type(ex).__name__}: {ex}"})
        out["charts"] = charts
        return out
