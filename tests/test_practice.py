"""tests/test_practice.py -- the improvement-loop endpoints: /api/practice,
/api/drill and /api/criteria/apply.

Written 2026-09-19 for the "wiring" stream of the UI refresh
(docs/UI_Refresh_Notes.md, Proposal C / "Turning analysis into improvement").
Drives a real server on an ephemeral port against a temporary store -- the
same isolation pattern as tests/test_server.py and tests/test_stats_page.py's
``isolated``/``sample``/``running_server`` fixtures (copied rather than
imported, per the convention already established in test_stats_page.py, so
this file has no import-time dependency on either).

Covers: GET /api/practice on an empty store (200, has_enough_data: False, a
message); the drill round trip (start a drill, submit it, the book position
is untouched, the history record is present and marked ``Drill: True``,
whether the drill is passed or failed); and POST /api/criteria/apply
rejecting a request that would lower a threshold.
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
    (bundled / "tiny.txt").write_text(
        "alpha line one\nbeta line two\ngamma line three\ndelta line four\n",
        encoding="utf-8",
    )
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
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    return status, raw


def _get_json(base_url, path):
    status, raw = _request(base_url, "GET", path)
    return status, json.loads(raw.decode("utf-8"))


def _post_json(base_url, path, body=None):
    status, raw = _request(base_url, "POST", path, body if body is not None else {})
    return status, json.loads(raw.decode("utf-8")) if raw else None


# ---- GET /api/practice on an empty store -------------------------------------------------


def test_practice_on_empty_store_is_usable_not_an_error(running_server):
    status, payload = _get_json(running_server, "/api/practice")
    assert status == 200
    assert payload["has_enough_data"] is False
    assert payload["message"]
    assert payload["targets"] == []
    assert payload["drill"] == ""
    assert payload["hard_lines"] == []
    assert payload["trouble_words"] == []
    # suggest_criteria always answers, even with nothing scored yet.
    assert "criteria_suggestion" in payload
    assert payload["criteria_suggestion"]["proposed_min_wpm"] == payload["criteria_suggestion"]["current_min_wpm"]


def test_practice_can_be_scoped_to_one_text(running_server):
    status, payload = _get_json(running_server, "/api/practice?text=tiny")
    assert status == 200
    assert payload["text_name"] == "tiny"


# ---- the drill round trip ------------------------------------------------------------------


def test_drill_leaves_book_position_untouched_on_pass(running_server):
    status, state = _get_json(running_server, "/api/state")
    assert status == 200
    start_position = state["position"]
    start_text = state["text_name"]
    book_line = state["current_line"]

    status, snap = _post_json(running_server, "/api/drill", {"line": "zebra quiz"})
    assert status == 200
    assert snap["in_drill"] is True
    assert snap["drill_line"] == "zebra quiz"
    assert snap["current_line"] == "zebra quiz"
    assert snap["position"] == start_position
    assert snap["state"] == "GAME"

    status, result = _post_json(running_server, "/api/attempt", {"typed": "zebra quiz", "duration_ms": 2000})
    assert status == 200
    assert result["result"]["passed"] is True
    assert result["result"]["position"] == start_position

    after = result["state"]
    assert after["in_drill"] is False
    assert after["drill_line"] is None
    assert after["position"] == start_position
    assert after["text_name"] == start_text
    assert after["current_line"] == book_line

    attempts = history.iter_attempts(start_text)
    drill_records = [r for _key, r in attempts if r.get("Drill")]
    assert len(drill_records) == 1
    assert drill_records[0]["Answer"] == "zebra quiz"
    assert drill_records[0]["user_input"] == "zebra quiz"
    assert drill_records[0]["Passed"] is True


def test_drill_leaves_book_position_untouched_on_fail(running_server):
    status, state = _get_json(running_server, "/api/state")
    start_position = state["position"]
    start_text = state["text_name"]
    book_line = state["current_line"]

    status, snap = _post_json(running_server, "/api/drill", {"line": "quick fox jump"})
    assert status == 200
    assert snap["position"] == start_position

    # Deliberately wrong, and slow, so it fails on both accuracy and wpm.
    status, result = _post_json(
        running_server, "/api/attempt", {"typed": "totally different text", "duration_ms": 20000}
    )
    assert status == 200
    assert result["result"]["passed"] is False
    assert result["result"]["position"] == start_position

    after = result["state"]
    assert after["in_drill"] is False
    assert after["position"] == start_position
    assert after["current_line"] == book_line

    attempts = history.iter_attempts(start_text)
    drill_records = [r for _key, r in attempts if r.get("Drill")]
    assert len(drill_records) == 1
    assert drill_records[0]["Passed"] is False


def test_drill_requires_a_line(running_server):
    status, payload = _post_json(running_server, "/api/drill", {"line": ""})
    assert status == 400
    assert "error" in payload

    status, payload = _post_json(running_server, "/api/drill", {})
    assert status == 400


# ---- POST /api/criteria/apply ---------------------------------------------------------------


def test_criteria_apply_rejects_lowering_min_wpm(running_server):
    status, settings = _get_json(running_server, "/api/settings")
    current_min_wpm = settings["min_wpm"]

    status, payload = _post_json(running_server, "/api/criteria/apply", {"min_wpm": current_min_wpm - 5})
    assert status == 400
    assert "lower" in payload["error"]

    status, settings_after = _get_json(running_server, "/api/settings")
    assert settings_after["min_wpm"] == current_min_wpm


def test_criteria_apply_rejects_lowering_min_accuracy(running_server):
    status, settings = _get_json(running_server, "/api/settings")
    current_min_accuracy = settings["min_accuracy"]

    status, payload = _post_json(
        running_server, "/api/criteria/apply", {"min_accuracy": max(0.0, current_min_accuracy - 0.1)}
    )
    assert status == 400
    assert "lower" in payload["error"]


def test_criteria_apply_accepts_a_raise(running_server):
    status, settings = _get_json(running_server, "/api/settings")
    new_min_wpm = settings["min_wpm"] + 5

    status, payload = _post_json(running_server, "/api/criteria/apply", {"min_wpm": new_min_wpm})
    assert status == 200
    assert payload["min_wpm"] == new_min_wpm

    status, settings_after = _get_json(running_server, "/api/settings")
    assert settings_after["min_wpm"] == new_min_wpm


def test_criteria_apply_requires_a_field(running_server):
    status, payload = _post_json(running_server, "/api/criteria/apply", {})
    assert status == 400
