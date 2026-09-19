"""config.py -- the six user-editable criteria settings, persisted as JSON.

Written 2026-09-19 for the "Paths and migration" stream of the repo's stage 4 refactor
(see docs/Refactor_Plan.md). Replaces the ad hoc load_config/save_config pair on the old
Game class (TypingTrainer.py, read-only reference). Verified by tests/test_config.py
(round-trip, missing-file, corrupt-file).

Defaults: TypingTrainer.py sets attribute defaults just above calling load_config()
(min_accuracy=1.0, min_wpm=20.0), and Game.load_config()'s own `.get(key, default)`
fallbacks agree with those. The repo's committed config.json on disk holds different,
already-customised values (min_accuracy=0.99, min_wpm=60.0) -- that is the user's saved
setting, not the code's default, so it is what migrate.py carries forward, not what
Settings() defaults to here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import paths


@dataclass
class Settings:
    require_accuracy: bool = True
    require_wpm: bool = True
    min_accuracy: float = 1.0
    min_wpm: float = 20.0
    show_criteria: bool = True
    flash_on_mistake: bool = True
    # Added 2026-09-19 with the UI refresh. Off by default: it changes how the
    # app feels to use, and the pass criteria already enforce accuracy per line.
    stop_on_error: bool = False
    live_stats: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        defaults = cls()
        return cls(
            require_accuracy=bool(data.get("require_accuracy", defaults.require_accuracy)),
            require_wpm=bool(data.get("require_wpm", defaults.require_wpm)),
            min_accuracy=float(data.get("min_accuracy", defaults.min_accuracy)),
            min_wpm=float(data.get("min_wpm", defaults.min_wpm)),
            show_criteria=bool(data.get("show_criteria", defaults.show_criteria)),
            flash_on_mistake=bool(data.get("flash_on_mistake", defaults.flash_on_mistake)),
            stop_on_error=bool(data.get("stop_on_error", defaults.stop_on_error)),
            live_stats=bool(data.get("live_stats", defaults.live_stats)),
        )


def settings_path():
    return paths.state_dir() / "settings.json"


def load() -> Settings:
    """Read settings.json, tolerating a missing or corrupt file by returning defaults
    and rewriting the file -- the same recovery behaviour as the old Game.load_config."""
    p = settings_path()
    if not p.exists():
        settings = Settings()
        save(settings)
        return settings
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        settings = Settings()
        save(settings)
        return settings
    settings = Settings.from_dict(data)
    return settings


def save(settings: Settings) -> None:
    settings_path().write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
