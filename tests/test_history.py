"""tests/test_history.py -- the SQLite attempt store: attempts, keystrokes, positions, legacy import.

Written 2026-09-19 for the "Paths and migration" stream of stage 4, and rewritten the
same day when the store moved from two JSON files to SQLite for the UI refresh (see
docs/UI_Refresh_Notes.md). TYPINGTRAINER_HOME is pointed at tmp_path in every test, so
nothing here can touch the real database.
"""

from __future__ import annotations

import json

import pytest

from typingtrainer import history


@pytest.fixture(autouse=True)
def _state_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path))


def _record(text_name="Art of War", **overrides):
    record = {
        "EventTime": "19-09-2026 10:00:00",
        "TextName": text_name,
        "Length": 23,
        "Duration": 4.2,
        "Accuracy": 1.0,
        "Wpm": 65.0,
        "Answer": "CHAPTER 1. LAYING PLANS",
        "user_input": "CHAPTER 1. LAYING PLANS",
        "user_input_full": "CHAPTER 1. LAYINXG PLANS",
    }
    record.update(overrides)
    return record


def _strokes(text="abc"):
    return [
        {"char": c, "ms": 100.0 * (i + 1), "correct": c != "b"}
        for i, c in enumerate(text)
    ]


def test_append_and_read_round_trips_every_field():
    key = history.append_attempt(_record(), key="2026-09-19T10:00:00")
    attempts = history.read_attempts()
    assert list(attempts) == [key]
    assert attempts[key] == _record()


def test_append_generates_a_unique_key_when_none_given():
    first = history.append_attempt(_record())
    second = history.append_attempt(_record())
    assert first != second
    assert len(history.read_attempts()) == 2


def test_unknown_fields_survive_the_round_trip():
    """An old record with a field nobody remembers must not be silently dropped."""
    key = history.append_attempt(_record(SomethingOld="keep me"), key="k1")
    assert history.read_attempts()[key]["SomethingOld"] == "keep me"


def test_passed_comes_back_as_a_bool():
    key = history.append_attempt(_record(Passed=True), key="k1")
    assert history.read_attempts()[key]["Passed"] is True
    key2 = history.append_attempt(_record(Passed=False), key="k2")
    assert history.read_attempts()[key2]["Passed"] is False


def test_keystrokes_are_stored_in_press_order():
    history.append_attempt(_record(), key="k1", keystrokes=_strokes("abc"))
    strokes = history.read_keystrokes("k1")
    assert [s["char"] for s in strokes] == ["a", "b", "c"]
    assert [s["ms"] for s in strokes] == [100.0, 200.0, 300.0]
    assert [s["correct"] for s in strokes] == [True, False, True]


def test_an_attempt_without_keystrokes_has_none():
    history.append_attempt(_record(), key="k1")
    assert history.read_keystrokes("k1") == []


def test_iter_attempts_is_ordered_and_filterable():
    history.append_attempt(_record("A"), key="2026-09-19T10:00:00")
    history.append_attempt(_record("B"), key="2026-09-19T09:00:00")
    history.append_attempt(_record("A"), key="2026-09-19T11:00:00")
    assert [k for k, _ in history.iter_attempts()] == [
        "2026-09-19T09:00:00",
        "2026-09-19T10:00:00",
        "2026-09-19T11:00:00",
    ]
    assert len(history.iter_attempts(text_name="A")) == 2
    assert len(history.iter_attempts(limit=1)) == 1


def test_iter_keystroke_attempts_returns_only_instrumented_ones():
    history.append_attempt(_record(), key="k1", keystrokes=_strokes("ab"))
    history.append_attempt(_record(), key="k2")
    history.append_attempt(_record(), key="k3", keystrokes=_strokes("cd"))
    got = history.iter_keystroke_attempts()
    assert [key for key, _r, _s in got] == ["k1", "k3"]
    assert [len(s) for _k, _r, s in got] == [2, 2]


def test_clear_history_by_text_takes_its_keystrokes_with_it():
    history.append_attempt(_record("A"), key="k1", keystrokes=_strokes())
    history.append_attempt(_record("B"), key="k2", keystrokes=_strokes())
    history.clear_history("A")
    assert list(history.read_attempts()) == ["k2"]
    assert history.read_keystrokes("k1") == []
    assert history.stats()["keystrokes"] == 3


def test_clear_history_all():
    history.append_attempt(_record("A"), key="k1", keystrokes=_strokes())
    history.clear_history()
    assert history.read_attempts() == {}
    assert history.stats() == {
        "attempts": 0,
        "keystrokes": 0,
        "instrumented": 0,
        "positions": 0,
    }


def test_positions_read_write_and_default():
    assert history.get_position("Art of War") == 0
    assert history.get_position("Art of War", default=7) == 7
    history.set_position("Art of War", 346)
    history.set_position("Art of War", 347)
    assert history.get_position("Art of War") == 347
    assert history.read_positions() == {"Art of War": 347}


def test_legacy_json_is_imported_once_on_first_use(tmp_path):
    """Upgrading the tool must not look like losing your history."""
    state = tmp_path
    (state / "history.json").write_text(
        json.dumps({"2026-09-01T08:00:00": _record("Art of War", Wpm=51.0)}),
        encoding="utf-8",
    )
    (state / "positions.json").write_text(
        json.dumps({"Art of War": 346}), encoding="utf-8"
    )

    attempts = history.read_attempts()
    assert len(attempts) == 1
    assert attempts["2026-09-01T08:00:00"]["Wpm"] == 51.0
    assert history.get_position("Art of War") == 346

    # The originals are left alone, and a second open does not import them again.
    assert (state / "history.json").exists()
    history.append_attempt(_record(), key="new")
    assert len(history.read_attempts()) == 2


def test_stats_counts_instrumented_attempts_separately():
    history.append_attempt(_record(), key="k1", keystrokes=_strokes("abcd"))
    history.append_attempt(_record(), key="k2")
    assert history.stats() == {
        "attempts": 2,
        "keystrokes": 4,
        "instrumented": 1,
        "positions": 0,
    }
