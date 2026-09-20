#!/usr/bin/env python
"""scripts/serve.py -- launch the web front end.

Written 2026-09-19 for the stage 5 "web server and API" stream of the repo's
refactor (see docs/Refactor_Plan.md). Thin by policy: argument parsing, an
environment-variable check, and one call into typingtrainer.web.server.

Verified by tests/test_server.py (which drives typingtrainer.web.server directly,
not this script) and by running this script by hand: `pixi run ui`.
"""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser

from typingtrainer.web import server as server_mod


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Serve the TypingTrainer web front end.")
    parser.add_argument("--port", type=int, default=0, help="TCP port; 0 (default) picks an ephemeral one.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind; 0.0.0.0 inside a container.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab.")
    args = parser.parse_args(argv)

    open_browser = not args.no_browser and not os.environ.get("TYPINGTRAINER_NO_BROWSER")

    httpd = server_mod.create_server(host=args.host, port=args.port)
    url = f"http://{httpd.server_address[0]}:{httpd.server_address[1]}/"
    print(url, flush=True)

    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
