"""Offline tests: schema helpers report names/types; the server exposes read tools only."""
import datetime as dt
import sys
from pathlib import Path

import pytest
from bson import ObjectId

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_server  # noqa: E402
from mongo_db import _collect_fields, _field_path  # noqa: E402

DOC = {
    "_id": ObjectId(),
    "name": "Sample",
    "amount": 1234.5,
    "createdAt": dt.datetime(2024, 1, 2),
    "address": {"city": "Chennai"},
    "lines": [{"sku": "A-1", "qty": 2}],
}


def test_schema_reports_paths_and_types():
    out = {}
    _collect_fields(DOC, "", out)
    assert out["_id"] == {"objectId"}
    assert out["name"] == {"string"}
    assert out["createdAt"] == {"date"}
    assert out["address.city"] == {"string"}
    assert out["lines[].qty"] == {"number"}


@pytest.mark.parametrize("path", ["status", "address.city", "lines[].qty", "customer_id"])
def test_field_paths_accepted(path):
    _field_path(path)


@pytest.mark.parametrize("path", ["", "$where", "a..b", "x.$gt"])
def test_bad_field_paths_rejected(path):
    with pytest.raises(ValueError):
        _field_path(path)


def test_read_tools_only():
    tools = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert {"list_collections", "infer_collection_schema", "get_inferred_relationships",
            "get_database_overview", "run_find", "run_aggregate", "get_distinct_values"} <= tools
    write_words = ("insert", "update", "delete", "remove", "drop", "replace", "create", "write", "bulk")
    assert not [t for t in tools if any(w in t.lower() for w in write_words)]


def test_client_never_calls_write_methods():
    source = (Path(__file__).resolve().parents[1] / "mongo_db.py").read_text(encoding="utf-8")
    for call in ("insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
                 "delete_many", "find_one_and_", "bulk_write", "drop(", "drop_collection", "create_collection",
                 "create_index", "drop_index", "rename("):
        assert call not in source, f"mongo_db.py must not call {call}"
