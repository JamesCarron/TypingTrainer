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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

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
        correct = entry.get("correct")
        cleaned.append(
            {
                "char": char,
                "ms": ms,
                "correct": None if correct is None else bool(correct),
            }
        )
    return cleaned


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


# (method, path) -> (handler, needs_body)
ROUTES = {
    ("GET", "/api/state"): _api_state,
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


def _assemble_page() -> str | None:
    """The page as one string, or None if the front end's files are not there yet."""
    page = TEMPLATES_DIR / "page.html"
    css = STATIC_DIR / "page.css"
    js = STATIC_DIR / "page.js"
    if not (page.is_file() and css.is_file() and js.is_file()):
        return None
    html = page.read_text(encoding="utf-8")
    html = html.replace("{{CSS}}", css.read_text(encoding="utf-8"))
    html = html.replace("{{JS}}", js.read_text(encoding="utf-8"))
    return html


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
        path = urlsplit(self.path).path
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
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/") :])
            return
        try:
            status, payload = _dispatch(self.server, "GET", path, {})
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
