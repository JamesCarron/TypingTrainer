"""config.py -- the user-editable criteria and display settings, persisted as JSON.

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

#: The typing line's width in characters (Wings v2, docs/mockups/UI_Mockup_Wings_v2.html
#: and docs/UI_Refresh_Notes.md). 50 is the floor the mockup settled on; 86 is the
#: ceiling because that is as wide as the line can get before it starts to crowd the
#: permanent left/right rails (``--rail``/``--panel`` in the mockup) -- past that the
#: measure would run under the wings rather than floating between them.
MEASURE_CH_MIN = 50
MEASURE_CH_MAX = 86
_MEASURE_CH_DEFAULT = 78


def _clamp_measure_ch(value) -> int:
    """Coerce to int and clamp to [MEASURE_CH_MIN, MEASURE_CH_MAX], defensively.

    Used by ``Settings.from_dict`` so a corrupt or hand-edited settings.json
    (a float, a string, a wildly out-of-range number) can never produce a
    ``Settings`` object outside the range the rails can actually display --
    the same defence-in-depth as the rest of ``from_dict``, which is why this
    exists here as well as the type/range check in ``POST /api/settings``.
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = _MEASURE_CH_DEFAULT
    return min(max(value, MEASURE_CH_MIN), MEASURE_CH_MAX)


@dataclass
class Settings:
    require_accuracy: bool = True
    require_wpm: bool = True
    min_accuracy: float = 1.0
    min_wpm: float = 20.0
    show_criteria: bool = True
    flash_on_mistake: bool = True
    # Added 2026-09-19 with the UI refresh, and switched on by default the same
    # day at the user's request: with a 99% accuracy floor a line with a mistake
    # is retyped anyway, so refusing the character does the same job without
    # spending the attempt, and it is what makes the keystroke error data
    # richest. Switch it off in Settings if it gets in the way.
    stop_on_error: bool = True
    live_stats: bool = True
    # Added 2026-09-20 for the Wings v2 UI refresh (docs/mockups/UI_Mockup_Wings_v2.html):
    # the typing line's width, in characters. See MEASURE_CH_MIN/MAX above for why
    # 86 is the ceiling.
    measure_ch: int = _MEASURE_CH_DEFAULT

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
            measure_ch=_clamp_measure_ch(data.get("measure_ch", defaults.measure_ch)),
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
