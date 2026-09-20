"""server.py -- the served web front end: one process, one Session, an ephemeral port.

Written 2026-09-19 for the stage 5 "web server and API" stream of the repo's refactor
(see docs/Refactor_Plan.md). The JSON API implemented here is fixed by
docs/Contracts.md -- that table is the source of truth, this module is the
implementation of it. Verified by tests/test_server.py, which drives every endpoint
over a real ephemeral-port server against a temporary state root.

Design notes that matter if this file is touched again:

* ``http.server.ThreadingHTTPServer`` serves requests concurrently, so every mutation
  of the single module-level ``Session`` takes ``STATE_LOCK`` first. Reads take it too,
  since ``snapshot()`` touches the same mutable Text object a concurrent write could be
  advancing.
* The page is assembled from real files on every ``GET /`` -- ``templates/page.html``
  with the literal placeholders ``{{CSS}}`` and ``{{JS}}`` filled from ``static/`` --
  read fresh each request so the other stream building those files can edit and just
  refresh the browser. Those three files did not exist when this module was written;
  a missing one degrades to a plain-text 503 rather than a crash.
* ``POST /api/pick_path`` never touches tkinter in this process. It shells out to
  ``python -m typingtrainer.web.picker <kind>`` (see picker.py) because a tkinter
  dialog blocks whatever thread opens it, and this server must keep answering other
  requests while one is open. A module-level lock rejects a second click while a
  dialog is already open rather than stacking dialogs.
* No exception may escape a handler as a bare 500 with a traceback: every route is
  called through ``_dispatch``, which maps known exception types to the 4xx status
  the contract specifies and anything else to a 400 with the exception's message.
"""

from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .. import analysis, config, drills, history
from .. import history
from ..session import Session, TextNotFound

PACKAGE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

#: Guards the native picker subprocess so a second click cannot stack dialogs.
PICKER_LOCK = threading.Lock()


class ApiError(Exception):
    """A request that fails cleanly with a specific HTTP status and message."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class TypingTrainerServer(ThreadingHTTPServer):
    """One Session per server instance (docs/Contracts.md says one per process; in
    practice that means one per ``create_server()`` call, which is what lets tests
    spin up an isolated server -- and therefore an isolated Session -- per test
    instead of sharing a module-level singleton across a whole test run).

    ``state_lock`` guards every read and every write of ``session``:
    ThreadingHTTPServer will happily serve two requests at once, and Session is not
    itself thread-safe.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = Session()
        self.state_lock = threading.RLock()


def _require(body: dict, key: str):
    if key not in body:
        raise ApiError(400, f"missing field: {key}")
    return body[key]


# ---- route handlers, each returning a JSON-serialisable value ----------------------


def _api_state(body, session: Session):
    return session.snapshot()


def _api_texts(body, session: Session):
    snap = session.snapshot()
    return {"texts": snap["texts"], "current": snap["text_name"]}


def _api_text(body, session: Session):
    name = _require(body, "name")
    try:
        session.select_text(name)
    except TextNotFound as exc:
        raise ApiError(400, f"no such text: {exc}") from exc
    return session.snapshot()


def _api_start(body, session: Session):
    session.start()
    return session.snapshot()


def _api_abort(body, session: Session):
    session.abort()
    return session.snapshot()


def _api_attempt(body, session: Session):
    typed = _require(body, "typed")
    duration_ms = _require(body, "duration_ms")
    if not isinstance(typed, str):
        raise ApiError(400, "typed must be a string")
    try:
        duration = float(duration_ms) / 1000.0
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "duration_ms must be a number") from exc
    keystrokes = _clean_keystrokes(body.get("keystrokes"))
    typed_full = body.get("typed_full")
    if typed_full is not None and not isinstance(typed_full, str):
        raise ApiError(400, "typed_full must be a string")
    try:
        result = session.submit_line(
            typed, duration, typed_full=typed_full, keystrokes=keystrokes
        )
    except RuntimeError as exc:
        raise ApiError(409, str(exc)) from exc
    return {"result": result.as_dict(), "state": session.snapshot()}


def _clean_keystrokes(raw):
    """Validate the per-keystroke record the page sends with an attempt.

    Rejected rather than coerced: a malformed timing list would quietly poison
    every latency statistic downstream, and a wrong number there is worse than
    no number. Absent is fine — attempts from before the instrumentation, and
    from any view that cannot capture it, simply have none.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ApiError(400, "keystrokes must be a list")
    if len(raw) > 10000:
        raise ApiError(400, "keystrokes: too many entries for one line")
    cleaned = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError(400, "keystrokes: each entry must be an object")
        char = entry.get("char")
        if not isinstance(char, str) or len(char) > 8:
            raise ApiError(400, "keystrokes: char must be a short string")
        try:
            ms = float(entry.get("ms", 0.0))
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "keystrokes: ms must be a number") from exc
        expected = entry.get("expected")
        if expected is not None and (not isinstance(expected, str) or len(expected) > 8):
            raise ApiError(400, "keystrokes: expected must be a short string or null")
        correct = entry.get("correct")
        cleaned.append(
            {
                "char": char,
                "expected": expected,
                "ms": ms,
                "correct": None if correct is None else bool(correct),
            }
        )
    return cleaned


def _parse_event_time(value):
    """Parse an ``EventTime`` string, defensively -- same formats history.py writes.

    Duplicated (rather than importing analysis._parse_event_time) so this module
    does not reach into another stream's private helpers; it is a handful of
    lines and the formats are pinned by docs/Contracts.md's history shape.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%d-%m-%Y %H:%M:%S")
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


#: A session is a run of attempts with no gap between consecutive ones larger
#: than this, ending at the most recent attempt overall -- see
#: ``_api_session_summary``.
SESSION_GAP = timedelta(minutes=30)


def _current_session_attempts() -> list:
    """The slice of ``history.iter_attempts()`` that makes up "the current session".

    Walks backward from the most recent attempt; the session boundary is the
    first gap (by ``EventTime``) larger than ``SESSION_GAP``, or an attempt
    whose time cannot be parsed (treated as its own boundary, since a gap
    cannot be measured to it). If no boundary is found the whole history is
    one session. All texts are considered together, not just the current one.
    """
    attempts = history.iter_attempts()
    if not attempts:
        return []
    start = 0
    for i in range(len(attempts) - 1, 0, -1):
        prev_t = _parse_event_time(attempts[i - 1][1].get("EventTime"))
        cur_t = _parse_event_time(attempts[i][1].get("EventTime"))
        if prev_t is None or cur_t is None or (cur_t - prev_t) > SESSION_GAP:
            start = i
            break
    return attempts[start:]


def _api_analysis(body, session: Session):
    text_name = body.get("text") or None
    return analysis.full_report(text_name=text_name)


def _api_session_summary(body, session: Session):
    """The attempts of the current session -- see ``_current_session_attempts``.

    Enriches ``analysis.session_summary`` (which only returns aggregate tiles
    plus a single best/worst line) with the full ordered WPM-per-line list, for
    the session summary's sparkline; that series is not something
    ``analysis.py`` returns, so it is assembled here from the same slice.
    """
    current = _current_session_attempts()
    summary = analysis.session_summary(current)
    summary["wpm_curve"] = [r.get("Wpm") for _key, r in current if r.get("Wpm") is not None]
    return summary


def _api_review(body, session: Session):
    """Everything the review screen (Wings v2 "option C", a moment -- see
    docs/mockups/UI_Mockup_Wings_v2.html and docs/UI_Refresh_Notes.md) needs
    after a session ends, in one call: the session summary (reusing
    ``_api_session_summary`` so there is exactly one place that assembles
    it, not two), what moved since last session (``analysis.session_deltas``,
    given the whole history so it can find and split out the last two
    sessions itself), one recommended next action
    (``analysis.next_action``, over the whole-history report -- weak points
    are a standing diagnosis, not scoped to one session), and the all-time
    streak (``analysis.overall_stats``, same whole-history reads, so this is
    a page-load call like ``/api/analysis``, not a per-keystroke one).

    Works and returns 200 against a completely empty store: every piece it
    calls already tolerates no data, so this needs no special case of its
    own (see the docstrings of ``session_deltas`` and ``next_action`` for how
    each degrades).
    """
    summary = _api_session_summary(body, session)
    all_attempts = history.iter_attempts()
    deltas = analysis.session_deltas(all_attempts)
    report = analysis.full_report()
    action = analysis.next_action(report)
    streak = analysis.overall_stats(all_attempts)
    return {
        "session_summary": summary,
        "deltas": deltas,
        "next_action": action,
        "streak": {
            "current_streak_days": streak["current_streak_days"],
            "longest_streak_days": streak["longest_streak_days"],
        },
    }


def _api_practice(body, session: Session):
    """The improvement-loop plan: weak targets, a drill, hard lines, the watchlist,
    and a criteria suggestion -- see ``drills.practice_plan``, the only store-touching
    function in that module. Reads the whole store, so this is a page-load call, like
    ``/api/analysis``, not a per-keystroke one."""
    text_name = body.get("text") or None
    return drills.practice_plan(text_name=text_name)


def _api_drill(body, session: Session):
    """Start a drill: make an arbitrary line (a generated drill, or a hard line
    picked from the book) the target for the player's very next attempt, without
    touching the book position or the saved text -- see ``Session.start_drill``."""
    line = _require(body, "line")
    if not isinstance(line, str):
        raise ApiError(400, "line must be a string")
    try:
        session.start_drill(line)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    return session.snapshot()


def _api_criteria_apply(body, session: Session):
    """Apply a ``drills.suggest_criteria`` proposal -- the engine only advises,
    this is where the user consents. Refuses anything that would lower a
    threshold below what is already set, since that is never what the
    suggestion itself proposes and a request that does so is either stale or
    wrong."""
    from dataclasses import asdict

    current = session.settings
    updates = {}
    if "min_wpm" in body:
        try:
            new_wpm = float(body["min_wpm"])
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "min_wpm must be a number") from exc
        if new_wpm < current.min_wpm:
            raise ApiError(
                400,
                f"refusing to lower min_wpm from {current.min_wpm} to {new_wpm}",
            )
        updates["min_wpm"] = new_wpm
    if "min_accuracy" in body:
        try:
            new_accuracy = float(body["min_accuracy"])
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "min_accuracy must be a number") from exc
        if new_accuracy < current.min_accuracy:
            raise ApiError(
                400,
                f"refusing to lower min_accuracy from {current.min_accuracy} to {new_accuracy}",
            )
        updates["min_accuracy"] = new_accuracy
    if not updates:
        raise ApiError(400, "expected min_wpm and/or min_accuracy")
    new_settings = session.update_settings(**updates)
    return asdict(new_settings)


def _api_position(body, session: Session):
    if "delta" in body:
        try:
            session.change_position(int(body["delta"]))
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "delta must be an integer") from exc
    elif "line" in body:
        try:
            session.jump_to(int(body["line"]))
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "line must be an integer") from exc
    else:
        raise ApiError(400, "expected 'delta' or 'line'")
    return session.snapshot()


def _api_settings_get(body, session: Session):
    from dataclasses import asdict

    return asdict(session.settings)


def _api_settings_post(body, session: Session):
    from dataclasses import asdict

    body = dict(body)
    if "measure_ch" in body:
        value = body["measure_ch"]
        # bool is an int subclass in Python; reject it explicitly rather than
        # silently storing True/False as 1/0 characters wide.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError(400, "measure_ch must be an integer")
        body["measure_ch"] = min(max(value, config.MEASURE_CH_MIN), config.MEASURE_CH_MAX)
    if "font_family" in body:
        value = body["font_family"]
        if not isinstance(value, str) or value not in config.FONT_FAMILIES:
            raise ApiError(
                400,
                "font_family must be one of: " + ", ".join(config.FONT_FAMILIES),
            )
    if "font_size_px" in body:
        value = body["font_size_px"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError(400, "font_size_px must be an integer")
        body["font_size_px"] = min(
            max(value, config.FONT_SIZE_PX_MIN), config.FONT_SIZE_PX_MAX
        )
    if "visible_lines" in body:
        value = body["visible_lines"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError(400, "visible_lines must be an integer")
        value = min(max(value, config.VISIBLE_LINES_MIN), config.VISIBLE_LINES_MAX)
        if value % 2 == 0:
            value += 1
            if value > config.VISIBLE_LINES_MAX:
                value -= 2
        body["visible_lines"] = value
    if "fade_per_line" in body:
        value = body["fade_per_line"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError(400, "fade_per_line must be a number")
        body["fade_per_line"] = min(
            max(float(value), config.FADE_PER_LINE_MIN), config.FADE_PER_LINE_MAX
        )
    if "error_style" in body:
        value = body["error_style"]
        if not isinstance(value, str) or value not in config.ERROR_STYLES:
            raise ApiError(
                400,
                "error_style must be one of: " + ", ".join(config.ERROR_STYLES),
            )
    try:
        new_settings = session.update_settings(**body)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    return asdict(new_settings)


def _api_history_reset(body, session: Session):
    scope = _require(body, "scope")
    try:
        removed = session.reset_history(scope)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    return {"removed": removed}


def _api_text_add(body, session: Session):
    path = _require(body, "path")
    try:
        name = session.add_text(path)
    except (ValueError, FileNotFoundError) as exc:
        raise ApiError(400, str(exc)) from exc
    return {"name": name, "state": session.snapshot()}


def _api_pick_path(body, session: Session):
    kind = _require(body, "kind")
    if kind not in ("file", "dir"):
        raise ApiError(400, "kind must be 'file' or 'dir'")
    if not PICKER_LOCK.acquire(blocking=False):
        raise ApiError(409, "a picker dialog is already open")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "typingtrainer.web.picker", kind],
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        PICKER_LOCK.release()
    try:
        result = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        result = {"error": proc.stderr.strip() or "the picker returned no usable output"}
    if not isinstance(result, dict) or ("path" not in result and "error" not in result):
        result = {"error": "the picker returned an unexpected result"}
    return result


#: A name has to fit on a rail and in a picker; anything longer is a mistake.
MAX_USER_NAME = 40


def _clean_user_name(raw) -> str:
    if not isinstance(raw, str):
        raise ApiError(400, "name must be a string")
    name = raw.strip()
    if not name:
        raise ApiError(400, "name must not be empty")
    if len(name) > MAX_USER_NAME:
        raise ApiError(400, f"name must be {MAX_USER_NAME} characters or fewer")
    return name


def _api_users(body, session: Session):
    return {"users": history.list_users(), "current": session.user}


def _api_user_post(body, session: Session):
    """Switch to a user, minting an anonymous one when the browser has none.

    Nothing blocks on being asked who you are: a browser that arrives with no
    remembered name asks for a guest here, starts typing immediately, and can
    put a real name on that progress later through the rename endpoint.
    """
    if body.get("anonymous"):
        name = history.next_guest_name()
        history.ensure_user(name, anonymous=True)
    else:
        name = _clean_user_name(body.get("name"))
    session.switch_user(name)
    return session.snapshot()


def _api_user_rename(body, session: Session):
    """Give a guest's progress a real name, keeping every attempt."""
    old = _clean_user_name(body.get("from"))
    new = _clean_user_name(body.get("to"))
    if old == new:
        return session.snapshot()
    try:
        history.rename_user(old, new)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    session.switch_user(new)
    return session.snapshot()


# (method, path) -> (handler, needs_body)
ROUTES = {
    ("GET", "/api/state"): _api_state,
    ("GET", "/api/users"): _api_users,
    ("POST", "/api/user"): _api_user_post,
    ("POST", "/api/user/rename"): _api_user_rename,
    ("GET", "/api/analysis"): _api_analysis,
    ("GET", "/api/session_summary"): _api_session_summary,
    ("GET", "/api/review"): _api_review,
    ("GET", "/api/practice"): _api_practice,
    ("POST", "/api/drill"): _api_drill,
    ("POST", "/api/criteria/apply"): _api_criteria_apply,
    ("GET", "/api/texts"): _api_texts,
    ("POST", "/api/text"): _api_text,
    ("POST", "/api/start"): _api_start,
    ("POST", "/api/abort"): _api_abort,
    ("POST", "/api/attempt"): _api_attempt,
    ("POST", "/api/position"): _api_position,
    ("GET", "/api/settings"): _api_settings_get,
    ("POST", "/api/settings"): _api_settings_post,
    ("POST", "/api/history/reset"): _api_history_reset,
    ("POST", "/api/text/add"): _api_text_add,
    ("POST", "/api/pick_path"): _api_pick_path,
}


def _dispatch(server: "TypingTrainerServer", method: str, path: str, body: dict) -> tuple[int, dict]:
    """Run one API route, mapping any exception to a JSON 4xx rather than a 500."""
    handler = ROUTES.get((method, path))
    if handler is None:
        return 404, {"error": f"no such route: {method} {path}"}
    with server.state_lock:
        session = server.session
        try:
            return 200, handler(body, session)
        except ApiError as exc:
            return exc.status, {"error": exc.message}
        except (TextNotFound, ValueError, FileNotFoundError) as exc:
            return 400, {"error": str(exc)}
        except RuntimeError as exc:
            return 409, {"error": str(exc)}
        except Exception as exc:  # last resort: never let a traceback reach the client
            return 400, {"error": f"{type(exc).__name__}: {exc}"}


def _assemble_from_files(
    page: Path, css: Path, js: Path, fonts: Path | None = None
) -> str | None:
    """One page as a string, filling ``{{CSS}}``/``{{JS}}`` (and, if given and
    present in the template, ``{{FONTS}}``) from the given files.

    Shared by ``_assemble_page`` (``GET /``) and ``_assemble_stats_page``
    (``GET /stats``) -- same read-fresh-every-request approach, so either
    front-end stream can edit its files and just refresh the browser. Returns
    None, degrading to a 503, if the page, css or js file is not there yet.

    ``fonts`` is optional and substituted only if the placeholder is actually
    present: the other stream is writing the template that will contain
    ``{{FONTS}}``, so this must tolerate a page.html that does not have it
    yet, and ``/stats`` never passes ``fonts`` at all since it does not need
    the embedded faces.
    """
    if not (page.is_file() and css.is_file() and js.is_file()):
        return None
    html = page.read_text(encoding="utf-8")
    if fonts is not None and "{{FONTS}}" in html:
        if not fonts.is_file():
            return None
        html = html.replace("{{FONTS}}", fonts.read_text(encoding="utf-8"))
    # {{FONTS}} is filled first so the page's own {{CSS}} rules -- substituted
    # next -- win over the embedded @font-face declarations, per the agreed
    # ordering (fonts, then page CSS, then JS).
    html = html.replace("{{CSS}}", css.read_text(encoding="utf-8"))
    html = html.replace("{{JS}}", js.read_text(encoding="utf-8"))
    return html


def _assemble_page() -> str | None:
    """The typing page as one string, or None if its front-end files are missing."""
    return _assemble_from_files(
        TEMPLATES_DIR / "page.html",
        STATIC_DIR / "page.css",
        STATIC_DIR / "page.js",
        STATIC_DIR / "fonts.css",
    )


def _assemble_stats_page() -> str | None:
    """The /stats page as one string, or None if its front-end files are missing."""
    return _assemble_from_files(
        TEMPLATES_DIR / "stats.html", STATIC_DIR / "stats.css", STATIC_DIR / "stats.js"
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "TypingTrainer/1.0"

    def log_message(self, fmt, *args):  # quieter default logging
        pass

    # -- plumbing -------------------------------------------------------------------

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, status: int, text: str, content_type: str = "text/plain") -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, f"invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ApiError(400, "request body must be a JSON object")
        return data

    # -- static files -----------------------------------------------------------------

    def _serve_static(self, rel_path: str) -> None:
        target = (STATIC_DIR / rel_path).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_json(404, {"error": "not found"})
            return
        if not target.is_file():
            self._send_json(404, {"error": "not found"})
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- verbs ------------------------------------------------------------------------

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/":
            html = _assemble_page()
            if html is None:
                self._send_text(
                    503,
                    "The TypingTrainer front end is not built yet "
                    "(templates/page.html, static/page.css and static/page.js).",
                )
                return
            self._send_text(200, html, content_type="text/html")
            return
        if path == "/stats":
            html = _assemble_stats_page()
            if html is None:
                self._send_text(
                    503,
                    "The TypingTrainer stats page is not built yet "
                    "(templates/stats.html, static/stats.css and static/stats.js).",
                )
                return
            self._send_text(200, html, content_type="text/html")
            return
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/") :])
            return
        # GET query params (e.g. /api/analysis?text=...) become the "body" dict
        # handed to the route -- GET has no JSON body, and this keeps every
        # handler's signature the same regardless of verb.
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            status, payload = _dispatch(self.server, "GET", path, query)
        except ApiError as exc:
            status, payload = exc.status, {"error": exc.message}
        self._send_json(status, payload)

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            body = self._read_json_body()
            status, payload = _dispatch(self.server, "POST", path, body)
        except ApiError as exc:
            status, payload = exc.status, {"error": exc.message}
        self._send_json(status, payload)


def create_server(host: str = "127.0.0.1", port: int = 0) -> TypingTrainerServer:
    """Build the server without starting it, so tests can bind, inspect the port,
    and run it in a background thread."""
    return TypingTrainerServer((host, port), Handler)


def serve_forever(host: str = "127.0.0.1", port: int = 0) -> None:
    """Start the server, print the URL it is listening on, and block."""
    httpd = create_server(host, port)
    url = f"http://{httpd.server_address[0]}:{httpd.server_address[1]}/"
    print(url, flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
