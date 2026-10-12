"""Offline tests: the chatbot is told today's date, and queries on a stale or future date are flagged."""
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chat_agent import ChatAgent, date_context, date_warning  # noqa: E402

NOW = dt.datetime(2026, 10, 12, 9, 30, tzinfo=dt.timezone.utc)


def _pipeline(iso: str) -> str:
    return json.dumps([{"$match": {"created_at": {"$gte": {"$date": iso}}}}, {"$group": {"_id": "$status"}}])


def test_context_gives_today_and_window_starts():
    text = date_context(NOW)
    assert "2026-10-12T09:30:00Z" in text
    assert "last 30 days: {\"$gte\": {\"$date\": \"2026-09-12T09:30:00Z\"}}" in text
    assert "this month: {\"$gte\": {\"$date\": \"2026-10-01T00:00:00Z\"}}" in text
    assert "this year: {\"$gte\": {\"$date\": \"2026-01-01T00:00:00Z\"}}" in text


def test_recent_date_is_fine():
    assert date_warning({"pipeline": _pipeline("2026-09-12T00:00:00Z")}, NOW) is None
    assert date_warning({"collection": "x"}, NOW) is None


def test_stale_date_from_model_memory_is_flagged():
    # The real failure: "last 30 days" became 2024-05-18, which matched every run.
    w = date_warning({"pipeline": _pipeline("2024-05-18T00:00:00Z")}, NOW)
    assert w and "days before today" in w and "2026-10-12" in w


def test_future_date_and_filter_argument_are_checked():
    w = date_warning({"filter": json.dumps({"uploaded_at": {"$lt": {"$date": "2027-03-01T00:00:00Z"}}})}, NOW)
    assert w and "in the future" in w


def test_chart_with_stale_date_is_held_back_once_then_allowed():
    class FakeSession:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return SimpleNamespace(
                structuredContent={"rows": [{"_id": "completed", "n": 1}], "row_count": 1},
                isError=False,
                content=[],
            )

    session = FakeSession()
    agent = ChatAgent.__new__(ChatAgent)
    charts = []
    args = {"title": "t", "chart_type": "bar", "collection": "extraction_results",
            "pipeline": _pipeline("2024-05-18T00:00:00Z"), "x_field": "_id", "y_fields": ["n"]}
    steps, warned = [], set()

    first, _ = asyncio.run(agent._call_tool("create_chart", dict(args), charts, steps, warned, session, set()))
    assert session.calls == [] and "date_warning" in first and '"charted": false' in first

    second, _ = asyncio.run(agent._call_tool("create_chart", dict(args), charts, steps, warned, session, set()))
    assert len(session.calls) == 1 and "date_warning" in second
    assert len(charts) == 1
