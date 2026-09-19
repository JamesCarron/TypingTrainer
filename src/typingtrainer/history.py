"""history.py -- the attempt store: past typing attempts and per-text line positions.

Written 2026-09-19 for the "Paths and migration" stream of the repo's stage 4 refactor
(see docs/Refactor_Plan.md). Replaces the pickled SaveGame.pickleddict on the old Game
class (TypingTrainer.py Game.save_game/load_game/log_game_history, read-only reference)
with two JSON files in the state dir. Verified by tests/test_history.py (append/read,
clear-one/clear-all, position read/write).

state_dir()/history.json   {<iso-8601 timestamp>: {record}, ...} -- JSON-safe replacement
                           for the pickle's {datetime: {record}} mapping. Record field
                           names are kept identical to the old log_game_history output
                           (EventTime, TextName, Length, Duration, Accuracy, Wpm, Answer,
                           user_input, user_input_full) so migrated and freshly-recorded
                           attempts are one dataset, not two shapes.
state_dir()/positions.json {<text name>: <line number>, ...} -- flattened out of the
                           pickle's {"Texts": {name: {"line": n}}} nesting, which existed
                           only because it shared a dict with History in one pickle.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import paths


def history_path() -> Path:
    return paths.state_dir() / "history.json"


def positions_path() -> Path:
    return paths.state_dir() / "positions.json"


def _read_json(p: Path, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def _write_json(p: Path, data) -> None:
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_attempts() -> dict:
    """All attempt records, keyed by ISO-8601 timestamp string."""
    return _read_json(history_path(), {})


def append_attempt(record: dict, key: str | None = None) -> str:
    """Add one attempt record and return the key it was stored under.

    ``key`` defaults to the current time to microsecond precision, which is what keeps
    two attempts submitted in the same second from colliding.
    """
    attempts = read_attempts()
    if key is None:
        key = datetime.now().isoformat()
        while key in attempts:
            key = datetime.now().isoformat()
    attempts[key] = record
    _write_json(history_path(), attempts)
    return key


def clear_history(text_name: str | None = None) -> None:
    """Clear all attempt history, or only the attempts for one text name."""
    if text_name is None:
        _write_json(history_path(), {})
        return
    attempts = read_attempts()
    attempts = {
        key: record
        for key, record in attempts.items()
        if record.get("TextName") != text_name
    }
    _write_json(history_path(), attempts)


def read_positions() -> dict:
    """All per-text line positions, keyed by text name."""
    return _read_json(positions_path(), {})


def get_position(text_name: str, default: int = 0) -> int:
    return int(read_positions().get(text_name, default))


def set_position(text_name: str, line: int) -> None:
    positions = read_positions()
    positions[text_name] = int(line)
    _write_json(positions_path(), positions)
