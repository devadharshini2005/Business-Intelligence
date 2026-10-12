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

from typing import Any

CHART_TYPES = ("bar", "hbar", "line", "pie", "doughnut", "table", "kpi")
MAX_SLICES = 8      # pie / doughnut: the rest folds into "Other"
MAX_POINTS = 200


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


def from_rows(title: str, chart_type: str, rows: list[dict[str, Any]], x_field: str,
              y_fields: list[str], series_names: list[str] | None = None, unit: str = "") -> dict[str, Any]:
    if chart_type not in CHART_TYPES:
        raise ValueError(f"chart_type must be one of {', '.join(CHART_TYPES)}")
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
