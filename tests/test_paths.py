"""tests/test_paths.py -- paths.py: TYPINGTRAINER_HOME redirection and folder creation.

Written 2026-09-19 for the "Paths and migration" stream of stage 4 (see
docs/Refactor_Plan.md). All assertions are against tmp_path via TYPINGTRAINER_HOME, so
nothing here ever touches the real %LOCALAPPDATA% or ~\\Documents.
"""

from __future__ import annotations

from pathlib import Path

import platformdirs

from typingtrainer import paths


def test_state_dir_honours_home_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path))
    result = paths.state_dir()
    assert result == tmp_path
    assert result.exists()


def test_cache_dir_is_under_home_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path))
    result = paths.cache_dir()
    assert result == tmp_path / "Cache"
    assert result.exists()


def test_state_and_cache_created_on_first_use(tmp_path, monkeypatch):
    home = tmp_path / "not_yet_created"
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(home))
    assert not home.exists()
    paths.state_dir()
    assert home.exists()
    paths.cache_dir()
    assert (home / "Cache").exists()


def test_documents_and_texts_dir_land_under_fake_documents_root(tmp_path, monkeypatch):
    # documents_dir()/texts_dir() are not redirected by TYPINGTRAINER_HOME (only state
    # and cache are), so the real platformdirs.user_documents_dir() call is monkeypatched
    # directly here -- otherwise this test would create a folder in the real ~/Documents.
    fake_documents_root = tmp_path / "Documents"
    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(fake_documents_root))
    docs = paths.documents_dir()
    texts = paths.texts_dir()
    assert docs == fake_documents_root / "TypingTrainer"
    assert docs.exists()
    assert texts.exists()
    assert texts == docs / "Texts"


def test_display_labels_known_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path))
    state = paths.state_dir()
    sub = state / "settings.json"
    label = paths.display(sub)
    assert label.startswith("[state]")
    assert "settings.json" in label


def test_display_never_raises_on_unrelated_path(tmp_path):
    unrelated = Path("Z:\\definitely\\not\\a\\known\\root\\file.txt")
    # Must not raise, whatever it returns.
    result = paths.display(unrelated)
    assert isinstance(result, str)


def test_describe_reports_home_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path))
    info = paths.describe()
    assert info["home_override"] == str(tmp_path)
    assert info["state"] == str(tmp_path)
