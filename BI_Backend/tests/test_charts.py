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


def test_mixed_scales_are_split_into_separate_charts():
    from charts import split_mixed_scales
    rows = [{"p": "A", "failed": 45, "rate": 0.37}, {"p": "B", "failed": 16, "rate": 0.15}]
    specs = split_mixed_scales(from_rows("Failures", "hbar", rows, "p", ["failed", "rate"], ["Failed", "Rate"]))
    assert [s["series"][0]["name"] for s in specs] == ["Failed", "Rate"]
    same = split_mixed_scales(from_rows("Runs", "bar", [{"p": "A", "a": 10, "b": 20}], "p", ["a", "b"]))
    assert len(same) == 1


def test_rates_between_0_and_1_become_percentages():
    from charts import as_percent
    spec = as_percent(from_rows("Failure rate by process", "bar", [{"p": "A", "r": 0.366}], "p", ["r"], ["Failure rate"]))
    assert spec["series"][0]["data"] == [36.6] and spec["unit"] == "%"
    counts = from_rows("Runs", "bar", [{"p": "A", "n": 1}], "p", ["n"])
    assert as_percent(counts) is counts


def test_long_rows_pivot_into_one_series_per_category_with_missing_days_as_zero():
    rows = [{"day": "2026-10-01", "source": "Email", "n": 3},
            {"day": "2026-10-01", "source": "Webhook", "n": 1},
            {"day": "2026-10-03", "source": "Email", "n": 2}]
    spec = from_rows("Per day", "line", rows, "day", ["n"], series_field="source")
    assert spec["labels"] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert spec["series"] == [{"name": "Email", "data": [3.0, 0, 2.0]}, {"name": "Webhook", "data": [1.0, 0, 0]}]
    gap = from_rows("Avg", "line", rows, "day", ["n"], series_field="source", missing_value="gap")
    assert gap["series"][1]["data"] == [1.0, None, None]


def test_rates_already_labelled_percent_are_still_scaled():
    from charts import as_percent
    spec = as_percent(from_rows("Success rate by process", "bar", [{"p": "A", "r": 0.816}], "p", ["r"], unit="%"))
    assert spec["series"][0]["data"] == [81.6]


def test_rate_kpi_stored_as_fraction_is_shown_as_percent():
    from charts import as_percent
    assert as_percent({"title": "Avg confidence", "type": "kpi", "value": 0.873}) == \
        {"title": "Avg confidence", "type": "kpi", "value": 87.3, "unit": "%"}
    # counts, values already in %, and non-rate titles are left alone
    assert as_percent({"title": "Failed runs", "type": "kpi", "value": 1})["value"] == 1
    assert as_percent({"title": "Avg confidence", "type": "kpi", "value": 87.3})["value"] == 87.3
