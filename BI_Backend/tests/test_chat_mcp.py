import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chat_agent import ChatAgent  # noqa: E402


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(structuredContent=self.payload, isError=False, content=[])


def test_chat_tool_dispatch_calls_mcp_server_and_returns_its_result():
    session = FakeSession({"rows": [{"collection": "runs"}], "row_count": 1})
    agent = ChatAgent.__new__(ChatAgent)
    steps = []

    content, is_error = asyncio.run(
        agent._call_tool("list_collections", {}, [], steps, set(), session, {"list_collections"})
    )

    assert not is_error
    assert '"collection": "runs"' in content
    assert session.calls == [("list_collections", {})]
    assert steps == [{"tool": "list_collections", "input": {}, "ok": True}]


def test_custom_chart_tool_runs_aggregation_through_mcp():
    session = FakeSession({"rows": [{"status": "completed", "runs": 3}], "row_count": 1})
    agent = ChatAgent.__new__(ChatAgent)
    charts, steps = [], []
    args = {"title": "Runs by status", "chart_type": "bar", "collection": "runs",
            "pipeline": "[]", "x_field": "status", "y_fields": ["runs"]}

    content, is_error = asyncio.run(
        agent._call_tool("create_chart", args, charts, steps, set(), session, set())
    )

    assert not is_error
    assert charts[0]["labels"] == ["completed"]
    assert session.calls == [("run_aggregate", {"collection": "runs", "pipeline": "[]", "max_rows": 200})]
    assert '"charted": true' in content
