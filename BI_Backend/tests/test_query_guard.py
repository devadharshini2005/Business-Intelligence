"""Unit tests for query_guard - no database connection needed."""
import sys
from pathlib import Path

import pytest
from bson import ObjectId

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from query_guard import (  # noqa: E402
    QueryGuardError,
    parse_filter,
    parse_pipeline,
    parse_projection,
    parse_sort,
)


def test_empty_filter_means_all():
    assert parse_filter("") == {}
    assert parse_filter("   ") == {}


def test_simple_filter_accepted():
    assert parse_filter('{"status": "open", "amount": {"$gt": 100}}') == {"status": "open", "amount": {"$gt": 100}}


def test_extended_json_accepted():
    oid = "65a1b2c3d4e5f60718293a4b"
    assert parse_filter('{"_id": {"$oid": "%s"}}' % oid) == {"_id": ObjectId(oid)}


def test_where_rejected_even_when_nested():
    with pytest.raises(QueryGuardError, match=r"\$where"):
        parse_filter('{"$and": [{"a": 1}, {"$where": "this.a > 1"}]}')


def test_filter_must_be_object():
    with pytest.raises(QueryGuardError, match="JSON object"):
        parse_filter("[1, 2]")


def test_invalid_json_rejected():
    with pytest.raises(QueryGuardError, match="not valid JSON"):
        parse_filter("{status: open}")


def test_read_pipeline_accepted():
    p = parse_pipeline('[{"$match": {"status": "open"}}, {"$group": {"_id": "$type", "n": {"$sum": 1}}}]')
    assert len(p) == 2


@pytest.mark.parametrize("stage", ['{"$out": "copy"}', '{"$merge": {"into": "copy"}}', '{"$OUT": "copy"}'])
def test_write_stages_rejected(stage):
    with pytest.raises(QueryGuardError, match="not allowed"):
        parse_pipeline(f'[{{"$match": {{}}}}, {stage}]')


def test_write_stage_inside_lookup_rejected():
    with pytest.raises(QueryGuardError, match=r"\$out"):
        parse_pipeline('[{"$lookup": {"from": "x", "as": "y", "pipeline": [{"$out": "z"}]}}]')


def test_server_side_js_rejected():
    with pytest.raises(QueryGuardError, match=r"\$function"):
        parse_pipeline('[{"$addFields": {"x": {"$function": {"body": "f", "args": [], "lang": "js"}}}}]')


def test_empty_pipeline_rejected():
    with pytest.raises(QueryGuardError, match="empty pipeline"):
        parse_pipeline("  ")


def test_pipeline_must_be_array():
    with pytest.raises(QueryGuardError, match="JSON array"):
        parse_pipeline('{"$match": {}}')


def test_projection_and_sort():
    assert parse_projection('{"name": 1, "_id": 0}') == {"name": 1, "_id": 0}
    assert parse_sort('{"createdAt": -1, "name": 1}') == [("createdAt", -1), ("name", 1)]
    assert parse_projection("") is None and parse_sort("") is None


def test_bad_sort_rejected():
    with pytest.raises(QueryGuardError, match="1/-1"):
        parse_sort('{"createdAt": "desc"}')
