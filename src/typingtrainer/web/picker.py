"""picker.py -- the native file/folder picker, run out-of-process.

Written 2026-09-19 for the stage 5 web server (see docs/Refactor_Plan.md and
docs/Contracts.md). A tkinter dialog blocks whatever thread calls it, and
``server.py`` runs on a ``ThreadingHTTPServer`` that must keep answering other
requests while the dialog is open -- so this module is never imported by the
server directly. Instead the server launches it as a subprocess
(``python -m typingtrainer.web.picker <kind>``) and reads one line of JSON back
from stdout. That also means a picker crash (no display, no tkinter, the user
has no desktop session) can never take the server down with it.

Verified by tests/test_server.py, which drives POST /api/pick_path with
tkinter's dialog functions monkeypatched (there is no display in CI).
"""

from __future__ import annotations

import json
import sys


def pick(kind: str) -> dict:
    """Run the native picker for ``kind`` ("file" or "dir") and return a result dict.

    Always returns a JSON-safe dict, never raises: ``{"path": str-or-None}`` on
    success (None means the user cancelled), or ``{"error": "<message>"}`` when
    tkinter or a display is unavailable.
    """
    if kind not in ("file", "dir"):
        return {"error": f"unknown picker kind: {kind}"}
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError as exc:
        return {"error": f"tkinter is not available: {exc}"}
    try:
        root = tkinter.Tk()
        root.withdraw()
        try:
            if kind == "file":
                chosen = filedialog.askopenfilename(
                    title="Choose a .txt file", filetypes=[("Text files", "*.txt")]
                )
            else:
                chosen = filedialog.askdirectory(title="Choose a folder")
        finally:
            root.destroy()
    except Exception as exc:  # no display, no window manager, etc.
        return {"error": f"could not open the native picker: {exc}"}
    return {"path": chosen or None}


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    print(json.dumps(pick(kind)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
