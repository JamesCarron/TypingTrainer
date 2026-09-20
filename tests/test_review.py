"""tests/test_review.py -- GET /api/review, the Wings v2 "option C" review screen's endpoint.

Written 2026-09-20 for the backend stream of the UI refresh
(docs/mockups/UI_Mockup_Wings_v2.html, docs/UI_Refresh_Notes.md). Drives a real
server on an ephemeral port against a temporary store -- the same isolation
pattern as tests/test_server.py's ``isolated``/``sample``/``running_server``
fixtures, copied rather than imported so this file has no import-time
dependency on that one (the convention AGENTS.md and test_server.py's own
docstring both call for).

Covers the three states the review screen must survive: an empty store, a
store holding exactly one session (nothing to compare against yet), and a
store holding two sessions separated by more than the session-gap threshold
(``analysis.SESSION_GAP_MINUTES``), where the deltas are real and hand-verified.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import platformdirs
import pytest

from typingtrainer import history, session as session_mod
from typingtrainer.web import server as server_mod


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(tmp_path / "docs"))
    return tmp_path


@pytest.fixture
def sample(isolated, monkeypatch):
    bundled = isolated / "bundled"
    bundled.mkdir()
    (bundled / "tiny.txt").write_text("alpha line\nbeta line\ngamma line\n", encoding="utf-8")
    monkeypatch.setattr(session_mod, "BUNDLED_DIR", bundled)
    monkeypatch.setattr(session_mod, "BUNDLED_NAMES", {})
    return bundled


@pytest.fixture
def running_server(sample):
    httpd = server_mod.create_server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{httpd.server_address[0]}:{httpd.server_address[1]}"
    try:
        yield base_url
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(base_url, path):
    req = urllib.request.Request(base_url + path)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    payload = json.loads(raw.decode("utf-8")) if raw else None
    return status, payload


def _attempt(event_time, wpm, accuracy, duration, answer="alpha line", typed=None):
    typed = answer if typed is None else typed
    return {
        "EventTime": event_time,
        "TextName": "tiny",
        "Length": len(answer),
        "Duration": duration,
        "Accuracy": accuracy,
        "Wpm": wpm,
        "Answer": answer,
        "user_input": typed,
        "user_input_full": typed,
        "Passed": typed == answer,
        "LineIndex": 0,
    }


# ---- empty store -----------------------------------------------------------


def test_review_on_empty_store(running_server):
    status, payload = _get(running_server, "/api/review")
    assert status == 200
    assert set(payload) == {"session_summary", "deltas", "next_action", "streak"}

    assert payload["session_summary"]["lines_completed"] == 0

    assert payload["deltas"]["has_previous"] is False
    assert payload["deltas"]["wpm"] == {
        "current": None,
        "previous": None,
        "delta": None,
        "direction": None,
    }
    assert payload["deltas"]["worst_category"]["category"] is None

    assert payload["next_action"]["kind"] is None
    assert "not enough data" in payload["next_action"]["message"]

    assert payload["streak"]["current_streak_days"] == 0
    assert payload["streak"]["longest_streak_days"] == 0


# ---- one session only: nothing to compare against yet -----------------------


def test_review_with_one_session_has_no_previous(running_server, isolated):
    history.append_attempt(_attempt("20-09-2026 09:00:00", 40.0, 0.9, 3.0))
    history.append_attempt(_attempt("20-09-2026 09:05:00", 50.0, 1.0, 4.0))

    status, payload = _get(running_server, "/api/review")
    assert status == 200
    assert payload["session_summary"]["lines_completed"] == 2

    deltas = payload["deltas"]
    assert deltas["has_previous"] is False
    assert deltas["wpm"]["current"] == pytest.approx(45.0)
    assert deltas["wpm"]["previous"] is None
    assert deltas["wpm"]["direction"] is None


# ---- two sessions, separated by more than the gap threshold ------------------


def test_review_with_two_sessions_reports_real_deltas(running_server, isolated):
    # Session 1 ("last session"): mean wpm 45, mean accuracy 0.95, 7s typing, 2 lines.
    history.append_attempt(_attempt("20-09-2026 09:00:00", 40.0, 0.9, 3.0))
    history.append_attempt(_attempt("20-09-2026 09:05:00", 50.0, 1.0, 4.0))

    # Session 2 ("this session"), more than SESSION_GAP_MINUTES (30) later:
    # mean wpm 65, mean accuracy 1.0, 4s typing, 2 lines.
    history.append_attempt(_attempt("20-09-2026 10:00:00", 60.0, 1.0, 2.0))
    history.append_attempt(_attempt("20-09-2026 10:05:00", 70.0, 1.0, 2.0))

    status, payload = _get(running_server, "/api/review")
    assert status == 200

    deltas = payload["deltas"]
    assert deltas["has_previous"] is True

    # hand-verified: current mean wpm (60+70)/2=65, previous (40+50)/2=45
    assert deltas["wpm"]["current"] == pytest.approx(65.0)
    assert deltas["wpm"]["previous"] == pytest.approx(45.0)
    assert deltas["wpm"]["delta"] == pytest.approx(20.0)
    assert deltas["wpm"]["direction"] == "up"

    # current mean accuracy 1.0, previous (0.9+1.0)/2=0.95
    assert deltas["accuracy"]["current"] == pytest.approx(1.0)
    assert deltas["accuracy"]["previous"] == pytest.approx(0.95)
    assert deltas["accuracy"]["direction"] == "up"

    # lines completed: 2 vs 2
    assert deltas["lines_completed"]["current"] == 2
    assert deltas["lines_completed"]["previous"] == 2
    assert deltas["lines_completed"]["direction"] == "same"

    # time typing: current 2+2=4s, previous 3+4=7s -- less time, "down"
    assert deltas["time_typing_s"]["current"] == pytest.approx(4.0)
    assert deltas["time_typing_s"]["previous"] == pytest.approx(7.0)
    assert deltas["time_typing_s"]["direction"] == "down"

    assert payload["session_summary"]["lines_completed"] == 2  # only "this session"
