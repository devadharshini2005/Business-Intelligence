"""Chart specs shared by the dashboard and the chatbot.

A chart spec is plain JSON the Angular app renders as-is:

  {"title": str, "type": "bar" | "hbar" | "line" | "pie" | "doughnut" | "table" | "kpi",
   "labels": [str], "series": [{"name": str, "data": [number | null]}],
   "columns": [str], "rows": [[any]],          # tables
   "value": number, "unit": str,               # kpi
   "note": str}

`from_rows` turns aggregation output into a spec, so every number in a chart
comes from a query that actually ran - never from text the model wrote.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

CHART_TYPES = ("bar", "hbar", "line", "pie", "doughnut", "table", "kpi")
MAX_SLICES = 8      # pie / doughnut: the rest folds into "Other"
MAX_POINTS = 200
MAX_ROWS = 1000     # long-format rows (one per label x series) before pivoting
MAX_FILL_DAYS = 400
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_path(row: dict[str, Any], path: str) -> Any:
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):  # relaxed extended JSON, e.g. {"$numberDecimal": "1.5"}
        value = next(iter(value.values()), None)
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _label(value: Any) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, dict):
        if "$date" in value:
            return str(value["$date"])[:10]
        if "$oid" in value:
            return value["$oid"]
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _fill_days(labels: list[str], series: list[dict[str, Any]], fill: float | None):
    """Daily labels ('2026-10-01'): sort them and add the missing days, so a day with no
    data shows as `fill` (0 for counts) instead of the line jumping over it."""
    if not labels or not all(DAY.match(l) for l in labels):
        return labels, series
    days = sorted(labels)
    start, end = dt.date.fromisoformat(days[0]), dt.date.fromisoformat(days[-1])
    if (end - start).days > MAX_FILL_DAYS:
        full = days
    else:
        full = [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    index = {l: i for i, l in enumerate(labels)}
    return full, [{**s, "data": [s["data"][index[d]] if d in index else fill for d in full]} for s in series]


def _pivot(rows: list[dict[str, Any]], x_field: str, y_field: str, series_field: str,
           fill: float | None) -> tuple[list[str], list[dict[str, Any]]]:
    """Long rows {day, source, count} -> labels (days) and one series per source."""
    labels = list(dict.fromkeys(_label(get_path(r, x_field)) for r in rows))
    values: dict[str, dict[str, float | None]] = {}
    for r in rows:
        cell = values.setdefault(_label(get_path(r, series_field)), {})
        x, y = _label(get_path(r, x_field)), _num(get_path(r, y_field))
        cell[x] = y if cell.get(x) is None else (cell[x] or 0) + (y or 0)  # duplicate rows add up
    return labels, [{"name": name, "data": [v.get(l, fill) for l in labels]} for name, v in values.items()]


def from_rows(title: str, chart_type: str, rows: list[dict[str, Any]], x_field: str,
              y_fields: list[str], series_names: list[str] | None = None, unit: str = "",
              series_field: str = "", missing_value: str = "zero") -> dict[str, Any]:
    """series_field: rows are 'long' (one row per label and series, e.g. day + source + count) -
    one series is made per distinct value of this field. missing_value: 'zero' (counts) or 'gap'
    (averages, rates) for labels a series has no row for, and for days missing from a date axis."""
    if chart_type not in CHART_TYPES:
        raise ValueError(f"chart_type must be one of {', '.join(CHART_TYPES)}")
    fill: float | None = None if missing_value == "gap" else 0
    if series_field and chart_type not in ("table", "kpi") and y_fields:
        labels, series = _pivot(rows[:MAX_ROWS], x_field, y_fields[0], series_field, fill)
        labels, series = _fill_days(labels, series, fill)
        spec = {"title": title, "type": chart_type, "labels": labels[-MAX_POINTS:],
                "series": [{**s, "data": s["data"][-MAX_POINTS:]} for s in series]}
        return {**spec, "unit": unit} if unit else spec
    rows = rows[:MAX_POINTS]
    names = series_names if series_names and len(series_names) == len(y_fields) else y_fields

    if chart_type == "kpi":
        field = y_fields[0] if y_fields else x_field
        return {"title": title, "type": "kpi", "value": _num(get_path(rows[0], field)) if rows else None,
                "unit": unit}

    if chart_type == "table":
        cols = ([x_field] if x_field else []) + list(y_fields)
        if not cols and rows:
            cols = list(rows[0].keys())
        return {"title": title, "type": "table", "columns": cols,
                "rows": [[_label(get_path(r, c)) if not isinstance(get_path(r, c), (int, float))
                          else get_path(r, c) for c in cols] for r in rows]}

    if not y_fields:
        raise ValueError("y_fields needs at least one numeric field")
    labels = [_label(get_path(r, x_field)) for r in rows]
    series = [{"name": n, "data": [_num(get_path(r, f)) for r in rows]} for f, n in zip(y_fields, names)]
    if chart_type in ("line", "bar"):
        labels, series = _fill_days(labels, series, fill)

    if chart_type in ("pie", "doughnut"):
        pairs = sorted(zip(labels, series[0]["data"]), key=lambda p: -(p[1] or 0))
        if len(pairs) > MAX_SLICES:
            other = sum(v or 0 for _, v in pairs[MAX_SLICES - 1:])
            pairs = pairs[:MAX_SLICES - 1] + [("Other", other)]
        labels = [p[0] for p in pairs]
        series = [{"name": series[0]["name"], "data": [p[1] for p in pairs]}]

    spec: dict[str, Any] = {"title": title, "type": chart_type, "labels": labels, "series": series}
    if unit:
        spec["unit"] = unit
    return spec


def split_mixed_scales(spec: dict[str, Any], ratio: float = 10.0) -> list[dict[str, Any]]:
    """One chart shows one kind of measure. If a chart's series differ in scale by more than
    `ratio` (e.g. run counts next to a 0-1 failure rate), return one chart per series instead,
    so the smaller measure isn't flattened against the shared axis."""
    series = spec.get("series") or []
    if spec.get("type") in ("table", "kpi") or len(series) < 2:
        return [spec]
    peaks = [max((abs(v) for v in s["data"] if v is not None), default=0) for s in series]
    nonzero = [p for p in peaks if p > 0]
    if len(nonzero) < 2 or max(nonzero) / min(nonzero) <= ratio:
        return [spec]
    return [{**spec, "title": f"{spec['title']} - {s['name']}", "series": [s]} for s in series]


RATE_NAME = re.compile(r"rate|ratio|percent|share|confidence|accuracy", re.I)


def as_percent(spec: dict[str, Any]) -> dict[str, Any]:
    """A single rate-like series stored as 0-1 (e.g. 'Failure rate' 0.366) is shown as 36.6 %."""
    series = spec.get("series") or []
    if len(series) != 1 or spec.get("unit") not in (None, "", "%") \
            or not RATE_NAME.search(f"{series[0]['name']} {spec['title']}"):
        return spec
    values = [v for v in series[0]["data"] if v is not None]
    if not values or not all(0 <= v <= 1 for v in values):
        return spec
    pct = [round(v * 100, 1) if v is not None else None for v in series[0]["data"]]
    return {**spec, "series": [{**series[0], "data": pct}], "unit": "%"}


def _when(value: Any) -> str:
    return str(value)[:16].replace("T", " ") if value else ""


def submission_table(sub: dict[str, Any]) -> dict[str, Any]:
    """idp_get_submission result -> one row per run (files without runs get a row too)."""
    rows = []
    for f in sub.get("files", []):
        runs = f.get("runs") or [None]
        for r in runs:
            attention = ", ".join(f"{n['name']} ({n['status']})" for n in (r or {}).get("needs_attention", []))
            current = (r or {}).get("current_step")
            rows.append([f.get("filename") or f.get("file_id"), f.get("status") or "",
                         (r or {}).get("process") or "-", (r or {}).get("status") or "no runs",
                         (r or {}).get("node_progress") or "",
                         attention or (f"{current['name']} ({current['status']})" if current else "")])
    return {"title": f"Files and runs of submission {sub.get('submission_id', '')}", "type": "table",
            "columns": ["file", "file status", "process", "run status", "steps", "current / needs attention"],
            "rows": rows}


def run_steps_table(run: dict[str, Any]) -> dict[str, Any]:
    """idp_get_run_details result -> one row per workflow step, in order."""
    rows = [[n.get("step"), n.get("name") or n.get("node_id"), n.get("status") or "",
             _when(n.get("started_at")), n.get("duration_s"),
             (n.get("error") or {}).get("reason") or (n.get("approval") or {}).get("decision") or ""]
            for n in run.get("nodes", [])]
    name = run.get("process") or "run"
    return {"title": f"Workflow steps - {name} (run {run.get('run_id', '')})", "type": "table",
            "columns": ["step", "name", "status", "started", "seconds", "error / approval"], "rows": rows}
