"""tests/test_stats_page.py -- the /stats page and its two analysis endpoints.

Written 2026-09-19 for the "analysis UI" stream of the UI refresh
(docs/UI_Refresh_Notes.md). Drives a real server on an ephemeral port against
a temporary store, the same isolation pattern as tests/test_server.py's
``isolated``/``sample``/``running_server`` fixtures (copied rather than
imported, so this file has no import-time dependency on that one).

Covers: GET /stats serves with {{CSS}}/{{JS}} substituted, GET /api/analysis
and GET /api/session_summary return the documented shapes both for an empty
store and once populated with synthetic attempts (some instrumented with
keystrokes, some not -- mirroring the mixed old/new data analysis.py is
written to tolerate), and the session-boundary logic in
``server._current_session_attempts``.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta

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


def _request(base_url, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base_url + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            raw = resp.read()
            content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
        content_type = exc.headers.get("Content-Type", "")
    return status, raw, content_type


def _get_json(base_url, path):
    status, raw, _ct = _request(base_url, "GET", path)
    return status, json.loads(raw.decode("utf-8"))


def _post(base_url, path, body=None):
    status, raw, _ct = _request(base_url, "POST", path, body if body is not None else {})
    return status, json.loads(raw.decode("utf-8")) if raw else None


def _seed_attempt(text_name, answer, typed, wpm, accuracy, passed, when, with_keystrokes):
    """Write one synthetic attempt straight to the store, bypassing the API,
    so the test controls EventTime precisely (for session-boundary tests) and
    can produce both instrumented and un-instrumented records."""
    record = {
        "EventTime": when.strftime("%d-%m-%Y %H:%M:%S"),
        "TextName": text_name,
        "Answer": answer,
        "user_input": typed,
        "user_input_full": typed,
        "Duration": 2.0,
        "Wpm": wpm,
        "Accuracy": accuracy,
        "Passed": passed,
        "Length": len(answer),
    }
    keystrokes = None
    if with_keystrokes:
        keystrokes = [
            {"char": ch, "ms": float(i * 80), "correct": (i < len(typed) and typed[i] == ch)}
            for i, ch in enumerate(answer)
        ]
    history.append_attempt(record, key=when.isoformat(), keystrokes=keystrokes)


# ---- /stats page ------------------------------------------------------------------------


def test_stats_page_serves_with_placeholders_substituted(running_server):
    status, raw, content_type = _request(running_server, "GET", "/stats")
    assert status == 200
    assert "text/html" in content_type
    body = raw.decode("utf-8")
    assert "{{CSS}}" not in body
    assert "{{JS}}" not in body
    assert "Stats" in body


def test_stats_page_503_when_front_end_missing(running_server, monkeypatch):
    monkeypatch.setattr(server_mod, "_assemble_stats_page", lambda: None)
    status, raw, content_type = _request(running_server, "GET", "/stats")
    assert status == 503
    assert "text/plain" in content_type


# ---- GET /api/analysis on an empty store -------------------------------------------------


def test_analysis_on_empty_store_is_usable_not_an_error(running_server):
    status, payload = _get_json(running_server, "/api/analysis")
    assert status == 200
    assert payload["data_coverage"]["total_attempts"] == 0
    assert payload["data_coverage"]["instrumented_attempts"] == 0
    # Every sub-report must still be present and well-shaped, not omitted.
    assert payload["weak_points"]["confusion_pairs"]["pairs"] == []
    assert payload["weak_points"]["character_error_rates"]["characters"] == []
    assert payload["speed"]["key_latencies"]["keys"] == []
    assert payload["progress"]["learning_curve"]["points"] == []
    assert payload["progress"]["overall_stats"]["total_attempts"] == 0
    assert payload["progress"]["overall_stats"]["current_streak_days"] == 0


def test_session_summary_on_empty_store_is_usable(running_server):
    status, payload = _get_json(running_server, "/api/session_summary")
    assert status == 200
    assert payload["lines_completed"] == 0
    assert payload["wpm_curve"] == []


# ---- populated store: mixed instrumented / non-instrumented attempts ----------------------


@pytest.fixture
def populated(running_server, isolated):
    now = datetime(2026, 9, 19, 10, 0, 0)
    # An older, un-instrumented session (a 40-minute gap before the next one).
    _seed_attempt("tiny", "alpha line", "alpha line", 40.0, 1.0, True, now, with_keystrokes=False)
    _seed_attempt(
        "tiny", "beta line", "beta lime", 35.0, 0.8, False, now + timedelta(seconds=30), with_keystrokes=False
    )
    # The current session: instrumented, starts more than 30 minutes later.
    session_start = now + timedelta(minutes=45)
    _seed_attempt("tiny", "alpha line", "alpha line", 50.0, 1.0, True, session_start, with_keystrokes=True)
    _seed_attempt(
        "tiny",
        "gamma line",
        "gamme line",
        60.0,
        0.9,
        True,
        session_start + timedelta(seconds=20),
        with_keystrokes=True,
    )
    return running_server


def test_analysis_reflects_populated_store(populated):
    status, payload = _get_json(populated, "/api/analysis")
    assert status == 200
    assert payload["data_coverage"]["total_attempts"] == 4
    assert payload["data_coverage"]["instrumented_attempts"] == 2
    # confusion_pairs should find the r/m substitutions from "beta lime"/"gamme line".
    pairs = payload["weak_points"]["confusion_pairs"]["pairs"]
    assert any(p["count"] >= 1 for p in pairs)
    # speed sections now have something to say, since 2 attempts are instrumented.
    assert payload["speed"]["key_latencies"]["instrumented_attempts"] == 2


def test_session_summary_is_only_the_current_session(populated):
    """The session boundary is a >30-minute gap; the fixture has exactly one,
    45 minutes before the two most recent attempts, so only those two should
    be in the summary even though four attempts exist in total."""
    status, payload = _get_json(populated, "/api/session_summary")
    assert status == 200
    assert payload["lines_completed"] == 2
    assert payload["passed"] == 2
    assert payload["failed"] == 0
    assert len(payload["wpm_curve"]) == 2
    assert payload["wpm_curve"] == [50.0, 60.0]
    assert payload["best_line"]["line"] == "gamma line"


def test_analysis_can_be_scoped_to_one_text(populated, isolated):
    # Seed a second text so the ?text= filter has something to exclude.
    history.append_attempt(
        {
            "EventTime": "19-09-2026 12:00:00",
            "TextName": "other",
            "Answer": "other line",
            "user_input": "other line",
            "user_input_full": "other line",
            "Duration": 2.0,
            "Wpm": 30.0,
            "Accuracy": 1.0,
            "Passed": True,
        },
        key="other-1",
    )
    status, payload = _get_json(populated, "/api/analysis?text=tiny")
    assert status == 200
    assert payload["data_coverage"]["text_name"] == "tiny"
    assert payload["data_coverage"]["total_attempts"] == 4

    status, payload = _get_json(populated, "/api/analysis?text=other")
    assert status == 200
    assert payload["data_coverage"]["total_attempts"] == 1
