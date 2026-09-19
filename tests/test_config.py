"""tests/test_config.py -- config.py: Settings round-trip, missing-file, corrupt-file.

Written 2026-09-19 for the "Paths and migration" stream of stage 4 (see
docs/Refactor_Plan.md). TYPINGTRAINER_HOME is pointed at tmp_path in every test, so
settings.json is never read or written anywhere but tmp_path.
"""

from __future__ import annotations

import pytest

from typingtrainer import config


@pytest.fixture(autouse=True)
def _state_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path))


def test_load_missing_file_returns_defaults_and_writes_it():
    assert not config.settings_path().exists()
    settings = config.load()
    assert settings == config.Settings()
    assert config.settings_path().exists()


def test_save_then_load_round_trips():
    original = config.Settings(
        require_accuracy=False,
        require_wpm=True,
        min_accuracy=0.95,
        min_wpm=45.0,
        show_criteria=False,
        flash_on_mistake=False,
    )
    config.save(original)
    loaded = config.load()
    assert loaded == original


def test_load_corrupt_file_returns_defaults_and_rewrites():
    config.settings_path().write_text("{not valid json", encoding="utf-8")
    settings = config.load()
    assert settings == config.Settings()
    # The corrupt file was replaced with something load() can now parse cleanly.
    reloaded = config.load()
    assert reloaded == config.Settings()


def test_from_dict_fills_missing_keys_with_defaults():
    settings = config.Settings.from_dict({"min_wpm": 80.0})
    defaults = config.Settings()
    assert settings.min_wpm == 80.0
    assert settings.min_accuracy == defaults.min_accuracy
    assert settings.require_accuracy == defaults.require_accuracy
