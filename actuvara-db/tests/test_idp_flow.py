"""Offline tests for idp_flow helpers - no database connection needed."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_server  # noqa: E402
from idp_flow import IdpFlow, _oid, rollup, workflow_order  # noqa: E402

# Shape of processes.workflow for "P&C Claims Processing": the trigger is stored
# last, and Fraud Screening has a back edge to Business Validations.
NODES = [{"id": i, "type": t} for i, t in [
    ("acu1", "action"), ("api1", "integration"), ("bre", "action"), ("fraud", "action"),
    ("decision", "action"), ("email", "integration"), ("trigger", "trigger")]]
EDGES = [{"source": s, "target": t} for s, t in [
    ("acu1", "api1"), ("api1", "bre"), ("bre", "fraud"), ("fraud", "decision"),
    ("decision", "email"), ("trigger", "acu1"), ("fraud", "bre")]]


def test_workflow_order_starts_at_trigger_and_ignores_back_edge():
    assert workflow_order(NODES, EDGES) == ["trigger", "acu1", "api1", "bre", "fraud", "decision", "email"]


def test_workflow_order_keeps_unconnected_nodes():
    order = workflow_order(NODES + [{"id": "orphan", "type": "action"}], EDGES)
    assert order[0] == "trigger" and "orphan" in order and len(order) == 8


@pytest.mark.parametrize("statuses, expected", [
    ([], "no_runs"),
    (["completed", "completed"], "completed"),
    (["completed", "skipped"], "completed"),
    (["completed", "failed"], "has_failures"),
    (["completed", "rejected"], "has_failures"),
    (["completed", "inprogress"], "in_progress"),
    (["completed", "awaiting_approval"], "in_progress"),
    (["completed", "not_started"], "mixed"),
])
def test_rollup(statuses, expected):
    assert rollup(statuses) == expected


def test_bad_ids_rejected():
    with pytest.raises(ValueError, match="24-character"):
        _oid("not-an-id")


def test_unknown_source_rejected():
    with pytest.raises(ValueError, match="source must be one of"):
        IdpFlow(db=None).find_submissions(source="fax")


def test_idp_tools_registered():
    tools = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert {"idp_find_submissions", "idp_get_submission", "idp_get_run_details"} <= tools
