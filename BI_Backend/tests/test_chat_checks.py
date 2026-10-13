"""Offline tests for the checks every chatbot answer must pass (chat_agent.py) - no model, no database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chat_agent import answer_problem, ids_in, is_empty, split_follow_ups, unverified_numbers  # noqa: E402

STEP = [{"tool": "run_aggregate", "input": {}, "ok": True, "empty": False}]
EMPTY_STEP = [{"tool": "run_aggregate", "input": {}, "ok": True, "empty": True}]
KPI = {"title": "Files", "type": "kpi", "value": 86}
BARS = {"title": "By status", "type": "bar", "labels": ["completed"], "series": [{"name": "n", "data": [86]}]}
SRC = ['{"rows": [{"n": 86}]}']


def test_follow_ups_are_split_from_the_answer():
    text, qs = split_follow_ups("There are 64 failed runs.\n\nFOLLOW_UPS: Which process fails most? | Per day?")
    assert text == "There are 64 failed runs." and qs == ["Which process fails most?", "Per day?"]
    assert split_follow_ups("No follow-ups.") == ("No follow-ups.", [])


def test_figures_need_a_query_and_a_chart_that_shows_them():
    assert "queried nothing" in answer_problem("A total of 1,234 files.", [], [], [])
    assert "no chart" in answer_problem("A total of 86 files.", STEP, [], SRC)
    # a "how many" question is answered by its headline number alone
    assert answer_problem("A total of 86 files.", STEP, [KPI], SRC) is None
    # more figures than headline numbers need a breakdown that shows them
    src = ['{"rows": [{"n": 86}, {"n": 50}, {"n": 36}]}']
    assert "breakdown" in answer_problem("86 files: 50 by email and 36 by webhook.", STEP, [KPI], src)
    assert answer_problem("A total of 86 files.", STEP, [KPI, BARS], SRC) is None
    # ids, dates and follow-ups are not figures
    assert answer_problem("File 6aa1a6d2cc50abb434e6e57d came on 2026-09-09.\nFOLLOW_UPS: Top 5?", [], [], []) is None


def test_none_found_is_rechecked_when_every_query_was_empty():
    assert "returned no data" in answer_problem("No files were processed.", EMPTY_STEP, [], [])
    assert answer_problem("No failed runs today.", STEP, [], []) is None


def test_a_trend_line_needs_three_points():
    line = {"title": "Per month", "type": "line", "labels": ["2026-09"], "series": [{"name": "n", "data": [85]}]}
    assert "fewer than 3 points" in answer_problem("85 files in September.", STEP, [line], ['{"n": 85}'])


def test_empty_results():
    assert is_empty({"rows": [], "row_count": 0}) and is_empty({"rows": [{"n": 0}], "row_count": 1})
    assert is_empty({"charts": [], "row_count": 0}) and is_empty({"document_count": 0})
    assert not is_empty({"rows": [{"n": 0}, {"n": 4}], "row_count": 2})


def test_figures_must_come_from_tool_results():
    src = ['{"row_count": 60}', '{"rows": [{"p": "UW", "failed": 45, "total": 123, "rate": 0.36585}]}', "last 30 days?"]
    assert unverified_numbers("There are 58 collections.", src) == ["58"]
    assert unverified_numbers("There are 60 collections.", src) == []
    assert unverified_numbers("45 of 123 failed (36.6%), rate 36.59%; top 5; last 90 days", src) == []
    assert unverified_numbers("It had 1,234 pages", src) == ["1,234"]
    assert ids_in({"$oid": "6AA1a6d2cc50abb434e6e57d"}) == {"6aa1a6d2cc50abb434e6e57d"}
