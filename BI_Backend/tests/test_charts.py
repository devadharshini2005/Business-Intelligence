"""Offline tests: chart specs are built only from query rows."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from charts import from_rows  # noqa: E402

ROWS = [{"_id": "completed", "n": 40, "avg": {"$numberDecimal": "0.91"}},
        {"_id": "failed", "n": 5, "avg": 0.4},
        {"_id": None, "n": 1, "avg": None}]


def test_bar_uses_row_values():
    spec = from_rows("Runs", "bar", ROWS, "_id", ["n", "avg"], ["Runs", "Avg"])
    assert spec["labels"] == ["completed", "failed", "(none)"]
    assert spec["series"][0] == {"name": "Runs", "data": [40.0, 5.0, 1.0]}
    assert spec["series"][1]["data"] == [0.91, 0.4, None]


def test_pie_folds_extra_slices_into_other():
    rows = [{"k": f"c{i}", "v": 20 - i} for i in range(12)]
    spec = from_rows("Share", "doughnut", rows, "k", ["v"])
    assert len(spec["labels"]) == 8 and spec["labels"][-1] == "Other"
    assert sum(spec["series"][0]["data"]) == sum(r["v"] for r in rows)


def test_kpi_and_table():
    assert from_rows("Total", "kpi", [{"n": 7}], "", ["n"])["value"] == 7.0
    t = from_rows("Rows", "table", [{"a": {"x": 1}, "b": 2}], "a.x", ["b"])
    assert t["columns"] == ["a.x", "b"] and t["rows"] == [[1, 2]]


def test_nested_dates_become_labels():
    spec = from_rows("Per day", "line", [{"_id": {"$date": "2026-10-01T00:00:00Z"}, "n": 3}], "_id", ["n"])
    assert spec["labels"] == ["2026-10-01"]


def test_bad_chart_type_rejected():
    with pytest.raises(ValueError):
        from_rows("x", "radar", ROWS, "_id", ["n"])
