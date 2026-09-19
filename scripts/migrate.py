#!/usr/bin/env python
"""scripts/migrate.py -- CLI wrapper around typingtrainer.migrate.migrate().

Written 2026-09-19 for the "Paths and migration" stream of the repo's stage 4 refactor
(see docs/Refactor_Plan.md). Argument parsing and one call into the package only; the
converter itself lives in src/typingtrainer/migrate.py. Verified by running it manually
against the real save file at the wave gate (not part of the automated test suite).
"""

from __future__ import annotations

import argparse
import sys

from typingtrainer import history, migrate, paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None, help="Repo root holding SaveGame.pickleddict and config.json (default: this repo)")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing non-empty history.json")
    args = parser.parse_args()

    try:
        result = migrate.migrate(repo_root=args.repo_root, force=args.force)
    except migrate.MigrationRefused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Nothing to migrate: {exc}", file=sys.stderr)
        return 1

    print(f"Source: {result['source_history_count']} history record(s), {result['source_texts_count']} text position(s).")
    print(f"Written: {result['written_history_count']} history record(s) to {history.history_path()}")
    print(f"Positions written to {history.positions_path()}")
    print(f"Settings written to {paths.state_dir() / 'settings.json'}")
    print()
    print("Source files were not touched. Once you have checked the counts above, it is")
    print("safe to remove SaveGame.pickleddict and config.json from the repo yourself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
