"""Offline tests for the BI API: read-only code, the routes the Angular app calls,
and the built frontend served at /."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import api_server  # noqa: E402

WRITE_CALLS = ("insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
               "delete_many", "find_one_and_", "bulk_write", "drop(", "drop_collection", "create_collection",
               "create_index", "drop_index", "rename(", '"$out"', '"$merge"')

client = TestClient(api_server.app)


@pytest.mark.parametrize("module", ["bi_analytics.py", "dashboard.py", "charts.py", "api_server.py"])
def test_modules_never_write(module):
    source = (ROOT / module).read_text(encoding="utf-8")
    for call in WRITE_CALLS:
        assert call not in source, f"{module} must not use {call}"


def test_routes_the_angular_app_calls_exist():
    paths = {getattr(r, "path", None) for r in api_server.app.routes}
    assert {"/api/health", "/api/chat", "/api/dashboard", "/api/overview", "/api/trend", "/api/processes",
            "/api/node-hotspots", "/api/collections", "/api/submissions", "/api/submissions/{submission_id}",
            "/api/runs/{run_id}"} <= paths


def test_chat_validates_the_conversation():
    assert client.post("/api/chat", json={"messages": []}).status_code == 422
    r = client.post("/api/chat", json={"messages": [{"role": "assistant", "content": "hi"}]})
    assert r.status_code == 400


def test_days_out_of_range_rejected():
    assert client.get("/api/overview?days=0").status_code == 422


def test_unknown_api_path_is_json_404():
    r = client.get("/api/nope")
    assert r.status_code == 404 and "detail" in r.json()


def test_root_serves_dashboard_or_build_hint():
    r = client.get("/")
    if (api_server.FRONTEND_DIST / "index.html").is_file():
        assert r.status_code == 200 and "<app-root" in r.text
    else:
        assert r.status_code == 503 and "npm run build" in r.text
