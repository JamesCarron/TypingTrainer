#!/usr/bin/env python
"""scripts/where.py -- print every resolved TypingTrainer data path.

Written 2026-09-19 for the "Paths and migration" stream of the repo's stage 4 refactor
(see docs/Refactor_Plan.md). Thin: argument parsing and one call into the package.
Verified by running it manually (`pixi run where`) and eyeballing the output.
"""

from __future__ import annotations

from pathlib import Path

from typingtrainer import history, paths


def main() -> int:
    for label, value in paths.describe().items():
        if not value:
            continue
        exists = "exists" if Path(value).exists() else "missing"
        print(f"{label:12} {value}  [{exists}]")

    db = history.db_path()
    print(f"{'database':12} {db}  [{'exists' if db.exists() else 'missing'}]")
    counts = history.stats()
    print(
        f"{'contents':12} {counts['attempts']} attempts, "
        f"{counts['instrumented']} of them with keystrokes "
        f"({counts['keystrokes']} keys), {counts['positions']} saved position(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
