"""tests/test_history.py -- history.py: append/read/clear attempts and positions.

Written 2026-09-19 for the "Paths and migration" stream of stage 4 (see
docs/Refactor_Plan.md). TYPINGTRAINER_HOME is pointed at tmp_path in every test.
"""

from __future__ import annotations

import pytest

from typingtrainer import history


@pytest.fixture(autouse=True)
def _state_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path))


def _record(text_name="Art of War", **overrides):
    record = {
        "EventTime": "19-09-2026 10:00:00",
        "TextName": text_name,
        "Length": 42,
        "Duration": 12.5,
        "Accuracy": 1.0,
        "Wpm": 55.0,
        "Answer": "some line of text",
        "user_input": "some line of text",
        "user_input_full": "some line of text",
    }
    record.update(overrides)
    return record


def test_read_attempts_empty_when_no_file():
    assert history.read_attempts() == {}


def test_append_and_read_attempt_round_trips():
    key = history.append_attempt(_record())
    attempts = history.read_attempts()
    assert key in attempts
    assert attempts[key]["TextName"] == "Art of War"
    assert attempts[key]["Wpm"] == 55.0


def test_append_two_attempts_get_distinct_keys():
    key1 = history.append_attempt(_record())
    key2 = history.append_attempt(_record())
    assert key1 != key2
    assert len(history.read_attempts()) == 2


def test_clear_history_one_text_only():
    history.append_attempt(_record(text_name="Art of War"))
    history.append_attempt(_record(text_name="Moby Dick"))
    history.clear_history(text_name="Art of War")
    remaining = history.read_attempts()
    assert len(remaining) == 1
    assert list(remaining.values())[0]["TextName"] == "Moby Dick"


def test_clear_history_all():
    history.append_attempt(_record(text_name="Art of War"))
    history.append_attempt(_record(text_name="Moby Dick"))
    history.clear_history()
    assert history.read_attempts() == {}


def test_position_defaults_to_zero():
    assert history.get_position("Art of War") == 0


def test_position_round_trips():
    history.set_position("Art of War", 346)
    assert history.get_position("Art of War") == 346
    assert history.read_positions() == {"Art of War": 346}


def test_position_for_unknown_text_uses_given_default():
    assert history.get_position("Nonexistent", default=7) == 7
