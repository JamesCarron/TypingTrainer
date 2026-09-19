"""migrate.py -- one-off converter from the old pickle+JSON persistence to the new state dir.

Written 2026-09-19 for the "Paths and migration" stream of the repo's stage 4 refactor
(see docs/Refactor_Plan.md). Reads the repo's SaveGame.pickleddict (a pickled dict of the
form {"Texts": {name: {"line": int}}, "History": {datetime: {record}}}, produced by the
old Game.save_game) and config.json (six settings), and writes settings.json,
history.json and positions.json into paths.state_dir() via config.py and history.py.

This is a format conversion (pickle -> JSON, datetime keys -> ISO-8601 strings), not a
move, so it is verified by comparing record counts on both sides, never by comparing
bytes. It never deletes the source files -- that is left to the human, after they have
looked at the printed counts. Verified by tests/test_migrate.py against a small
synthetic pickle (never the user's real save file).
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from . import config, history, paths


class MigrationRefused(RuntimeError):
    """Raised when history.json already holds data and --force was not given."""


def _load_pickle(save_path: Path) -> dict:
    with open(save_path, "rb") as f:
        return pickle.load(f)


def _load_config_json(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def migrate(
    repo_root: Path | None = None,
    save_path: Path | None = None,
    config_path: Path | None = None,
    force: bool = False,
) -> dict:
    """Convert the pickle + config.json into the new state-dir JSON files.

    Returns a dict of {"source_history_count", "source_texts_count", "written_history_count"}
    for the caller to print/verify. Raises MigrationRefused if history.json already has
    records and ``force`` is False. Raises FileNotFoundError if the pickle is missing.
    """
    root = Path(repo_root) if repo_root else paths.REPO
    save_path = Path(save_path) if save_path else root / "SaveGame.pickleddict"
    config_path = Path(config_path) if config_path else root / "config.json"

    if not save_path.exists():
        raise FileNotFoundError(f"No save file at {save_path}")

    existing_history = history.read_attempts()
    if existing_history and not force:
        raise MigrationRefused(
            f"{history.history_path()} already has {len(existing_history)} record(s); "
            "pass --force to overwrite."
        )

    save_data = _load_pickle(save_path)
    source_texts = save_data.get("Texts", {})
    source_history = save_data.get("History", {})

    # Settings: repo config.json's own values (the user's saved customisation),
    # falling back to Settings() defaults for anything missing.
    config_data = _load_config_json(config_path)
    settings = config.Settings.from_dict(config_data)
    config.save(settings)

    # History: datetime keys (or any non-string key) become ISO-8601 strings so the
    # file is JSON-safe; string keys already produced by a prior migration pass through.
    converted_history = {}
    for key, record in source_history.items():
        key_str = key.isoformat() if hasattr(key, "isoformat") else str(key)
        converted_history[key_str] = record
    history._write_json(history.history_path(), converted_history)

    # Positions: flatten {"Texts": {name: {"line": n}}} to {name: n}.
    positions = {
        name: info.get("line", 0) if isinstance(info, dict) else info
        for name, info in source_texts.items()
    }
    history._write_json(history.positions_path(), positions)

    return {
        "source_history_count": len(source_history),
        "source_texts_count": len(source_texts),
        "written_history_count": len(converted_history),
    }
