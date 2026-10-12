"""Offline tests: chart_metric charts the dashboard's own numbers, with names as labels."""
import sys
from pathlib import Path

import pytest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from charts import from_rows  # noqa: E402
from chat_agent import ChatAgent, OPENAI_TOOLS, metric_rows  # noqa: E402


class FakeBi:
    def overview(self, days):
        return {"current": {"runs_by_status": {"completed": 95, "failed": 12, "rejected": 1},
                            "submissions_by_source": {"email": 3, "webhook": 0, "manual_upload": 5}}}

    def processes(self, days, limit=12):
        return [{"name": "P&C Claims Processing", "runs": 54, "completed": 50, "failed": 4}]

    def node_hotspots(self, days, limit=10):
        return [{"name": "Policy lookup", "process": "P&C Claims Processing", "total": 58,
                 "by_status": {"failed": 58}}]

    def trend(self, days):
        return {"sources": ["email", "webhook"], "rows": [{"date": "2026-10-11", "email": 1, "webhook": 2, "runs": 4}]}


def test_status_pie_uses_dashboard_counts():
    rows, x, ys, names, title = metric_rows(FakeBi(), "runs_by_status", 30)
    spec = from_rows(title, "pie", rows, x, ys, names)
    assert spec["labels"] == ["completed", "failed", "rejected"] and spec["series"][0]["data"] == [95, 12, 1]
    assert "last 30 days" in spec["title"]


def test_labels_are_names_not_ids():
    assert metric_rows(FakeBi(), "runs_by_process", 30)[0][0]["process"] == "P&C Claims Processing"
    assert metric_rows(FakeBi(), "failing_nodes", 90)[0][0]["node"] == "Policy lookup (P&C Claims Processing)"
    assert [r["source"] for r in metric_rows(FakeBi(), "submissions_by_source", 7)[0]] == ["Email", "Webhook",
                                                                                         "Manual upload"]


def test_per_day_metric_has_one_series_per_source():
    rows, x, ys, names, _ = metric_rows(FakeBi(), "submissions_per_day", 7)
    assert x == "date" and ys == ["email", "webhook"] and names == ["Email", "Webhook"]


def test_unknown_metric_rejected_and_tool_is_offered():
    with pytest.raises(ValueError):
        metric_rows(FakeBi(), "revenue", 30)
    assert "create_chart" in {t["function"]["name"] for t in OPENAI_TOOLS}
    mcp_tools = [SimpleNamespace(name="chart_metric", description="Chart a tested dashboard metric",
                                 inputSchema={"type": "object", "properties": {}})]
    offered = ChatAgent._openai_tool_specs(mcp_tools)
    assert "chart_metric" in {t["function"]["name"] for t in offered}
