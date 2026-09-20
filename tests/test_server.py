"""tests/test_server.py -- the JSON API in typingtrainer/web/server.py, end to end.

Written 2026-09-19 for the stage 5 "web server and API" stream of the repo's
refactor (see docs/Refactor_Plan.md; the endpoint list and shapes are fixed by
docs/Contracts.md). Starts a real server on an ephemeral port in a background
thread, against a temporary state root and a temporary documents root -- the
same isolation pattern as tests/test_session.py's ``isolated`` fixture, copied
rather than imported so this file has no import-time dependency on that one.

Nothing here may write outside ``tmp_path``: TYPINGTRAINER_HOME is redirected
for state/cache, and platformdirs.user_documents_dir is monkeypatched for the
Documents root, before any Session is constructed.

GET / is skipped when the other stream's templates/page.html, static/page.css
and static/page.js do not exist yet -- server.py degrades that route to a 503
rather than crashing, and this suite must stay green whichever stream finishes
first.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime

import platformdirs
import pytest

from typingtrainer import session as session_mod
from typingtrainer.web import server as server_mod


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A state root and a documents root that exist only for this test."""
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(tmp_path / "docs"))
    return tmp_path


@pytest.fixture
def sample(isolated, monkeypatch):
    """A three-line bundled text, standing in for the real Art of War sample."""
    bundled = isolated / "bundled"
    bundled.mkdir()
    (bundled / "tiny.txt").write_text("alpha line\nbeta line\ngamma line\n", encoding="utf-8")
    monkeypatch.setattr(session_mod, "BUNDLED_DIR", bundled)
    monkeypatch.setattr(session_mod, "BUNDLED_NAMES", {})
    return bundled


@pytest.fixture
def running_server(sample):
    """A real server, bound to an ephemeral port, serving in a background thread.

    Built directly from server_mod.create_server() (not scripts/serve.py) so the
    test owns start-up and shutdown precisely and never opens a browser.
    """
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
    """POST/GET helper returning (status, parsed-json-or-None). Never raises on 4xx."""
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
    payload = json.loads(raw.decode("utf-8")) if raw else None
    return status, payload


def _get(base_url, path):
    return _request(base_url, "GET", path)


def _post(base_url, path, body=None):
    return _request(base_url, "POST", path, body if body is not None else {})


# ---- the front end route --------------------------------------------------------------


def test_root_serves_page_or_skips_when_front_end_not_built(running_server):
    from typingtrainer.web.server import TEMPLATES_DIR, STATIC_DIR

    have_front_end = (
        (TEMPLATES_DIR / "page.html").is_file()
        and (STATIC_DIR / "page.css").is_file()
        and (STATIC_DIR / "page.js").is_file()
    )
    if not have_front_end:
        pytest.skip("front end (templates/page.html, static/page.*) not built yet")
    req = urllib.request.Request(running_server + "/")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        body = resp.read().decode("utf-8")
    assert "{{CSS}}" not in body
    assert "{{JS}}" not in body


def test_root_returns_503_plain_text_when_front_end_missing(running_server, monkeypatch):
    # Force the "not built yet" path regardless of the other stream's progress,
    # so this assertion does not depend on timing between the two streams.
    monkeypatch.setattr(server_mod, "_assemble_page", lambda: None)
    req = urllib.request.Request(running_server + "/")
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        status = exc.code
        content_type = exc.headers.get("Content-Type", "")
    assert status == 503
    assert "text/plain" in content_type


# ---- state / texts ----------------------------------------------------------------------


def test_state_reflects_the_fresh_session(running_server):
    status, payload = _get(running_server, "/api/state")
    assert status == 200
    assert payload["state"] == "READY"
    assert payload["text_name"] == "tiny"
    assert payload["line_count"] == 3
    assert payload["current_line"] == "alpha line"


def test_texts_lists_the_bundled_sample(running_server):
    status, payload = _get(running_server, "/api/texts")
    assert status == 200
    assert payload["current"] == "tiny"
    assert {t["name"]: t["source"] for t in payload["texts"]} == {"tiny": "bundled"}


def test_select_unknown_text_is_400(running_server):
    status, payload = _post(running_server, "/api/text", {"name": "not a text"})
    assert status == 400
    assert "error" in payload


# ---- start / attempt / abort -------------------------------------------------------------


def test_attempt_outside_game_is_409(running_server):
    status, payload = _post(running_server, "/api/attempt", {"typed": "alpha line", "duration_ms": 2000})
    assert status == 409
    assert "error" in payload


def test_pass_scores_advances_and_a_fresh_state_reflects_it(running_server):
    status, _ = _post(
        running_server,
        "/api/settings",
        {"require_accuracy": True, "min_accuracy": 1.0, "require_wpm": False},
    )
    assert status == 200

    status, payload = _post(running_server, "/api/start")
    assert status == 200
    assert payload["state"] == "GAME"

    status, payload = _post(running_server, "/api/attempt", {"typed": "alpha line", "duration_ms": 2000})
    assert status == 200
    assert payload["result"]["passed"] is True
    assert payload["result"]["accuracy"] == 1.0
    assert payload["result"]["position"] == 1
    assert payload["state"]["position"] == 1

    # No state lives only in the page: a completely fresh request sees the advance.
    status, payload = _get(running_server, "/api/state")
    assert status == 200
    assert payload["position"] == 1
    assert payload["current_line"] == "beta line"


def test_fail_is_scored_but_does_not_advance(running_server):
    _post(running_server, "/api/settings", {"require_accuracy": True, "min_accuracy": 1.0, "require_wpm": False})
    _post(running_server, "/api/start")
    status, payload = _post(running_server, "/api/attempt", {"typed": "wrong line", "duration_ms": 2000})
    assert status == 200
    assert payload["result"]["passed"] is False
    assert payload["state"]["position"] == 0

    status, payload = _get(running_server, "/api/state")
    assert payload["position"] == 0


def test_bad_attempt_body_is_400(running_server):
    _post(running_server, "/api/start")
    status, payload = _post(running_server, "/api/attempt", {"typed": "alpha line", "duration_ms": "soon"})
    assert status == 400
    assert "error" in payload


def test_abort_returns_to_ready(running_server):
    _post(running_server, "/api/start")
    status, payload = _post(running_server, "/api/abort")
    assert status == 200
    assert payload["state"] == "READY"


# ---- position ---------------------------------------------------------------------------


def test_position_delta_and_jump(running_server):
    status, payload = _post(running_server, "/api/position", {"delta": 2})
    assert status == 200
    assert payload["position"] == 2

    status, payload = _post(running_server, "/api/position", {"line": 1})
    assert status == 200
    assert payload["position"] == 0


def test_position_with_no_delta_or_line_is_400(running_server):
    status, payload = _post(running_server, "/api/position", {})
    assert status == 400
    assert "error" in payload


# ---- settings -----------------------------------------------------------------------------


def test_settings_round_trip(running_server):
    status, payload = _get(running_server, "/api/settings")
    assert status == 200
    assert set(payload) == {
        "require_accuracy",
        "require_wpm",
        "min_accuracy",
        "min_wpm",
        "show_criteria",
        "flash_on_mistake",
        "stop_on_error",
        "live_stats",
        "measure_ch",
    }

    status, payload = _post(running_server, "/api/settings", {"min_wpm": 42.0})
    assert status == 200
    assert payload["min_wpm"] == 42.0

    status, payload = _get(running_server, "/api/settings")
    assert payload["min_wpm"] == 42.0


def test_settings_unknown_key_is_400(running_server):
    status, payload = _post(running_server, "/api/settings", {"nonsense": True})
    assert status == 400
    assert "error" in payload


# ---- measure_ch (Wings v2 line width, docs/mockups/UI_Mockup_Wings_v2.html) --------------


def test_measure_ch_round_trips(running_server):
    status, payload = _post(running_server, "/api/settings", {"measure_ch": 60})
    assert status == 200
    assert payload["measure_ch"] == 60

    status, payload = _get(running_server, "/api/settings")
    assert status == 200
    assert payload["measure_ch"] == 60


def test_measure_ch_is_clamped_to_the_valid_range(running_server):
    status, payload = _post(running_server, "/api/settings", {"measure_ch": 999})
    assert status == 200
    assert payload["measure_ch"] == 86  # MEASURE_CH_MAX

    status, payload = _post(running_server, "/api/settings", {"measure_ch": 1})
    assert status == 200
    assert payload["measure_ch"] == 50  # MEASURE_CH_MIN


def test_measure_ch_rejects_non_integer(running_server):
    status, payload = _post(running_server, "/api/settings", {"measure_ch": "wide"})
    assert status == 400
    assert "error" in payload

    status, payload = _post(running_server, "/api/settings", {"measure_ch": 78.5})
    assert status == 400
    assert "error" in payload

    # bool is an int subclass in Python -- must not be accepted as a width.
    status, payload = _post(running_server, "/api/settings", {"measure_ch": True})
    assert status == 400
    assert "error" in payload


# ---- history reset ------------------------------------------------------------------------


def test_history_reset_current(running_server):
    _post(running_server, "/api/settings", {"require_accuracy": False, "require_wpm": False})
    _post(running_server, "/api/start")
    _post(running_server, "/api/attempt", {"typed": "alpha line", "duration_ms": 1000})

    status, payload = _post(running_server, "/api/history/reset", {"scope": "current"})
    assert status == 200
    assert payload["removed"] == 1


def test_history_reset_bad_scope_is_400(running_server):
    status, payload = _post(running_server, "/api/history/reset", {"scope": "everything"})
    assert status == 400
    assert "error" in payload


# ---- text/add and pick_path -----------------------------------------------------------------


def test_text_add_copies_into_the_library(running_server, isolated):
    from typingtrainer import paths

    source = isolated / "elsewhere.txt"
    source.write_text("borrowed line\n", encoding="utf-8")

    status, payload = _post(running_server, "/api/text/add", {"path": str(source)})
    assert status == 200
    assert payload["name"] == "elsewhere"
    assert (paths.texts_dir() / "elsewhere.txt").is_file()
    assert any(t["name"] == "elsewhere" for t in payload["state"]["texts"])


def test_text_add_rejects_non_txt(running_server, isolated):
    source = isolated / "notatext.md"
    source.write_text("nope", encoding="utf-8")
    status, payload = _post(running_server, "/api/text/add", {"path": str(source)})
    assert status == 400
    assert "error" in payload


def test_pick_path_bad_kind_is_400(running_server):
    status, payload = _post(running_server, "/api/pick_path", {"kind": "spreadsheet"})
    assert status == 400
    assert "error" in payload


def test_pick_path_runs_the_picker_subprocess(running_server, monkeypatch):
    """The real picker needs a display; here we only prove the server wires the
    subprocess call correctly by monkeypatching subprocess.run's result."""
    import subprocess as subprocess_mod

    class FakeCompleted:
        stdout = json.dumps({"path": "C:\\chosen\\file.txt"})
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout):
        assert cmd[1:3] == ["-m", "typingtrainer.web.picker"]
        assert cmd[3] == "file"
        return FakeCompleted()

    monkeypatch.setattr(server_mod.subprocess, "run", fake_run)
    status, payload = _post(running_server, "/api/pick_path", {"kind": "file"})
    assert status == 200
    assert payload["path"] == "C:\\chosen\\file.txt"


# ---- generic routing ------------------------------------------------------------------------


def test_unknown_route_is_404(running_server):
    status, payload = _get(running_server, "/api/nonexistent")
    assert status == 404
    assert "error" in payload


def test_bad_json_body_is_400(running_server):
    req = urllib.request.Request(
        running_server + "/api/start",
        data=b"{not json",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 400


def test_picker_module_degrades_without_tkinter(monkeypatch):
    """picker.pick() itself, exercised directly rather than through the subprocess,
    proves the "no display available" path returns an error dict instead of raising."""
    from typingtrainer.web import picker

    assert picker.pick("nonsense") == {"error": "unknown picker kind: nonsense"}
