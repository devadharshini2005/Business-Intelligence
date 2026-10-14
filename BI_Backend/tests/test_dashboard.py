"""Offline tests for the Analytics page's pure logic (dashboard.py) - no database connection needed."""
import datetime as dt
import sys
from pathlib import Path

import pytest
from bson import ObjectId

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import IST, Scope, _delta, _pct  # noqa: E402


def test_change_vs_previous_period():
    assert _delta(15, 10, "count") == 0.5          # counts: relative change
    assert _delta(56.2, 40.0, "points") == 16.2    # rates: percentage points
    assert _delta(5, 0, "count") is None           # nothing to compare with
    assert _delta(5, None, "count") is None        # "all time" has no previous period


def test_percent_of_nothing_is_unknown_not_zero():
    assert _pct(3, 4) == 75.0
    assert _pct(0, 0) is None


def test_period_starts_at_ist_midnight_and_previous_period_is_the_same_length():
    s = Scope(30, "", "")
    assert s.start.tzinfo == IST and s.start.time() == dt.time.min
    assert s.start - s.prev_start == dt.timedelta(days=30)
    assert Scope(0, "", "").start is None


def test_scope_filters_runs_with_the_stored_field_names():
    pid = ObjectId()
    m = Scope(7, "webhook", str(pid)).runs()
    assert m["proccess_id"] == pid                 # sic - extraction_results spells it this way
    assert m["webhook_id"] == {"$exists": True, "$ne": None}


def test_bad_filters_are_rejected():
    with pytest.raises(ValueError):
        Scope(30, "fax", "")
    with pytest.raises(ValueError):
        Scope(30, "", "not-an-id")
