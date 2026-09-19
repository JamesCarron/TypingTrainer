"""tests/test_migrate.py -- migrate.py: pickle+config.json -> state-dir JSON.

Written 2026-09-19 for the "Paths and migration" stream of stage 4 (see
docs/Refactor_Plan.md). Builds a small SYNTHETIC pickle shaped like the real
SaveGame.pickleddict (confirmed 2026-09-19 against the actual file: a dict with "Texts"
and "History" keys, "History" keyed by datetime objects) -- never the user's real save
data. TYPINGTRAINER_HOME is pointed at tmp_path in every test.
"""

from __future__ import annotations

import pickle
from datetime import datetime

import pytest

from typingtrainer import config, history, migrate


@pytest.fixture(autouse=True)
def _state_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path))


def _write_synthetic_save(root):
    save_data = {
        "Texts": {"Art of War": {"line": 12}},
        "History": {
            datetime(2026, 1, 1, 9, 0, 0): {
                "EventTime": "01-01-2026 09:00:00",
                "TextName": "Art of War",
                "Length": 10,
                "Duration": 5.0,
                "Accuracy": 1.0,
                "Wpm": 60.0,
                "Answer": "line one",
                "user_input": "line one",
                "user_input_full": "line one",
            },
            datetime(2026, 1, 1, 9, 5, 0): {
                "EventTime": "01-01-2026 09:05:00",
                "TextName": "Art of War",
                "Length": 8,
                "Duration": 4.2,
                "Accuracy": 0.9,
                "Wpm": 48.0,
                "Answer": "line two",
                "user_input": "line too",
                "user_input_full": "line too",
            },
        },
    }
    save_path = root / "SaveGame.pickleddict"
    with open(save_path, "wb") as f:
        pickle.dump(save_data, f)

    config_path = root / "config.json"
    config_path.write_text(
        '{"require_accuracy": true, "require_wpm": true, "min_accuracy": 0.99, '
        '"min_wpm": 60.0, "show_criteria": true, "flash_on_mistake": true}',
        encoding="utf-8",
    )
    return save_path, config_path


def test_migrate_converts_counts_and_a_spot_checked_record(tmp_path):
    _write_synthetic_save(tmp_path)

    result = migrate.migrate(repo_root=tmp_path)

    assert result["source_history_count"] == 2
    assert result["source_texts_count"] == 1
    assert result["written_history_count"] == 2

    attempts = history.read_attempts()
    assert len(attempts) == 2
    record = attempts["2026-01-01T09:00:00"]
    assert record["TextName"] == "Art of War"
    assert record["Wpm"] == 60.0
    assert record["Answer"] == "line one"

    positions = history.read_positions()
    assert positions == {"Art of War": 12}

    settings = config.load()
    assert settings.min_accuracy == 0.99
    assert settings.min_wpm == 60.0


def test_migrate_missing_pickle_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        migrate.migrate(repo_root=tmp_path)


def test_migrate_refuses_to_overwrite_nonempty_history_without_force(tmp_path):
    _write_synthetic_save(tmp_path)
    migrate.migrate(repo_root=tmp_path)

    with pytest.raises(migrate.MigrationRefused):
        migrate.migrate(repo_root=tmp_path)


def test_migrate_force_overwrites_existing_history(tmp_path):
    _write_synthetic_save(tmp_path)
    migrate.migrate(repo_root=tmp_path)

    result = migrate.migrate(repo_root=tmp_path, force=True)
    assert result["written_history_count"] == 2


def test_migrate_never_deletes_source_files(tmp_path):
    save_path, config_path = _write_synthetic_save(tmp_path)
    migrate.migrate(repo_root=tmp_path)
    assert save_path.exists()
    assert config_path.exists()
