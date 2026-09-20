"""tests/test_session.py -- the headless engine: state machine, scoring path, persistence.

Written 2026-09-19 for the stage 3 engine extraction (see docs/Refactor_Plan.md). Every
test runs against a temporary state root (TYPINGTRAINER_HOME) and a temporary documents
root (platformdirs.user_documents_dir monkeypatched), so nothing here touches the real
%LOCALAPPDATA% or ~\\Documents. The first test is the structural one: if session.py ever
imports tkinter again, the split has been undone and the web front end has to grow a
second copy of the game logic.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import platformdirs
import pytest

from typingtrainer import config, history, session as session_mod
from typingtrainer.session import Session, TextNotFound


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A state root and a documents root that exist only for this test."""
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(tmp_path / "docs"))
    return tmp_path


@pytest.fixture
def sample(isolated, monkeypatch):
    """A three-line text, standing in for the bundled sample."""
    bundled = isolated / "bundled"
    bundled.mkdir()
    (bundled / "tiny.txt").write_text("alpha line\nbeta line\ngamma line\n", encoding="utf-8")
    monkeypatch.setattr(session_mod, "BUNDLED_DIR", bundled)
    monkeypatch.setattr(session_mod, "BUNDLED_NAMES", {})
    return bundled


def test_session_module_does_not_import_tkinter():
    """The structural guarantee the whole refactor rests on."""
    source = Path(session_mod.__file__).read_text(encoding="utf-8")
    imports = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    # No GUI toolkit may appear in an import line; a mention in prose is fine.
    assert not [line for line in imports if "tkinter" in line or "PIL" in line], imports


def test_loads_the_only_text_and_starts_ready(sample):
    s = Session()
    assert s.state == "READY"
    assert s.text_name == "tiny"
    assert s.line_count == 3
    assert s.current_line() == "alpha line"
    assert s.visible_lines() == ["alpha line", "beta line", "gamma line"]


def test_invalid_state_raises(sample):
    s = Session()
    with pytest.raises(ValueError):
        s.set_state("PLAYING")


def test_submit_outside_game_raises(sample):
    s = Session()
    with pytest.raises(RuntimeError):
        s.submit_line("alpha line", 1.0)


def test_perfect_line_passes_advances_and_persists(sample):
    s = Session()
    s.update_settings(require_accuracy=True, min_accuracy=1.0, require_wpm=False)
    s.start()
    result = s.submit_line("alpha line", 2.0, when=datetime(2026, 9, 19, 10, 0, 0))
    assert result.passed is True
    assert result.accuracy == 1.0
    assert result.position == 1
    assert s.current_line() == "beta line"
    assert history.get_position("tiny") == 1
    attempts = history.read_attempts()
    assert len(attempts) == 1
    record = next(iter(attempts.values()))
    assert record["TextName"] == "tiny"
    assert record["Answer"] == "alpha line"
    assert record["Length"] == len("alpha line")


def test_failed_line_is_logged_but_does_not_advance(sample):
    s = Session()
    s.update_settings(require_accuracy=True, min_accuracy=1.0, require_wpm=False)
    s.start()
    result = s.submit_line("alpha lion", 2.0)
    assert result.passed is False
    assert result.position == 0
    assert s.current_line() == "alpha line"
    assert len(history.read_attempts()) == 1
    assert history.read_positions().get("tiny", 0) == 0


def test_wpm_criterion_can_fail_a_perfect_line(sample):
    s = Session()
    s.update_settings(require_accuracy=True, min_accuracy=1.0, require_wpm=True, min_wpm=1000.0)
    s.start()
    result = s.submit_line("alpha line", 5.0)
    assert result.accuracy == 1.0
    assert result.passed is False


def test_abort_discards_without_logging(sample):
    s = Session()
    s.start()
    s.abort()
    assert s.state == "READY"
    assert history.read_attempts() == {}


def test_position_moves_are_clamped_and_persisted(sample):
    s = Session()
    s.change_position(5)
    assert s.position == 2
    s.change_position(-99)
    assert s.position == 0
    s.jump_to(3)
    assert s.position == 2
    assert history.get_position("tiny") == 2
    assert s.state == "READY"


def test_position_is_restored_on_a_new_session(sample):
    Session().jump_to(2)
    assert Session().position == 1


def test_settings_are_validated_and_saved(sample):
    s = Session()
    s.update_settings(min_accuracy=5.0, min_wpm=-3)
    assert s.settings.min_accuracy == 1.0
    assert s.settings.min_wpm == 0.0
    assert config.load().min_accuracy == 1.0
    with pytest.raises(ValueError):
        s.update_settings(nonsense=True)


def test_reset_history_scopes(sample):
    s = Session()
    s.update_settings(require_accuracy=False, require_wpm=False)
    s.start()
    s.submit_line("alpha line", 2.0, when=datetime(2026, 9, 19, 10, 0, 0))
    s.start()
    s.submit_line("beta line", 2.0, when=datetime(2026, 9, 19, 10, 0, 1))
    assert len(history.read_attempts()) == 2
    assert s.reset_history("current") == 2
    assert history.read_attempts() == {}
    with pytest.raises(ValueError):
        s.reset_history("everything")


def test_user_library_text_is_found_and_selectable(sample, isolated):
    from typingtrainer import paths

    (paths.texts_dir() / "mine.txt").write_text("my own line\n", encoding="utf-8")
    s = Session()
    names = {t["name"]: t["source"] for t in s.snapshot()["texts"]}
    assert names == {"tiny": "bundled", "mine": "library"}
    s.select_text("mine")
    assert s.current_line() == "my own line"
    with pytest.raises(TextNotFound):
        s.select_text("not a text")


def test_add_text_copies_into_the_library(sample, isolated, tmp_path):
    from typingtrainer import paths

    source = tmp_path / "elsewhere.txt"
    source.write_text("borrowed line\n", encoding="utf-8")
    name = Session().add_text(source)
    assert name == "elsewhere"
    assert (paths.texts_dir() / "elsewhere.txt").is_file()
    assert source.is_file()  # the original is left where it was
    with pytest.raises(ValueError):
        Session().add_text(tmp_path / "notatext.md")


def test_snapshot_has_everything_a_view_needs(sample):
    snap = Session().snapshot()
    assert set(snap) == {
        "state",
        "text_name",
        "position",
        "line_count",
        "progress",
        "visible_lines",
        "previous_lines",
        "current_line",
        "in_drill",
        "drill_line",
        "settings",
        "texts",
        "last_result",
    }
    assert snap["last_result"] is None


def test_preceding_lines_fills_the_view_above_the_current_line(sample):
    """The reading surface shows the book above the current line too, and the
    page may not invent that text -- it has to come from the engine."""
    s = Session()
    s.jump_to(3)                      # 1-based, so index 2: "gamma line"
    assert s.current_line() == "gamma line"
    assert s.preceding_lines() == ["alpha line", "beta line"]
    assert s.snapshot()["previous_lines"] == ["alpha line", "beta line"]


def test_preceding_lines_is_empty_at_the_start_of_a_text(sample):
    """Nothing precedes line zero, and that is not an error."""
    s = Session()
    assert s.position == 0
    assert s.preceding_lines() == []


def test_preceding_lines_is_capped(sample, isolated, monkeypatch):
    """The cap exists so a long book does not ship its whole history in every
    snapshot; the view never asks for more than half of visible_lines."""
    s = Session()
    s.jump_to(3)
    assert s.preceding_lines(n=1) == ["beta line"]
