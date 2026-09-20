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
MEASURE_CH_MAX = 120  # raised from 86 on 2026-09-20: the page now clamps
#: the measure to the space between the rails with a CSS min(), so a higher
#: ceiling simply means the top of the slider reaches them on a wide screen
#: instead of stopping short. On a narrow one it reads as "full".
_MEASURE_CH_DEFAULT = 78


#: The reading surface's font choices (docs/mockups/UI_Mockup_Reader_C.html,
#: "Advanced" settings panel), chosen by the user against the live prototype --
#: do not add or remove one without going back to that mockup. The first three
#: are proportional; the last three are fixed-width. FONT_IS_MONO exposes that
#: split to the page, which needs it: a proportional face cannot substitute a
#: typed character for the book's without the line reflowing, so the page must
#: know which regime it is in.
FONT_FAMILIES = (
    "Open Sans",
    "Work Sans",
    "Public Sans",
    "Fira Code",
    "Roboto Mono",
    "Ubuntu Mono",
)
FONT_IS_MONO = {
    "Open Sans": False,
    "Work Sans": False,
    "Public Sans": False,
    "Fira Code": True,
    "Roboto Mono": True,
    "Ubuntu Mono": True,
}
_FONT_FAMILY_DEFAULT = "Open Sans"

#: Reading-surface type size, in pixels, for the current (largest) line --
#: the other visible lines are this size scaled down by CSS. Range and
#: default from the same Reader C prototype session.
FONT_SIZE_PX_MIN = 13
FONT_SIZE_PX_MAX = 26
_FONT_SIZE_PX_DEFAULT = 17

#: How many book lines are shown at once, current line in the middle -- must
#: be odd so the split above/below it is even. Range and default from the
#: Reader C prototype.
VISIBLE_LINES_MIN = 3
VISIBLE_LINES_MAX = 15
_VISIBLE_LINES_DEFAULT = 5

#: Geometric fade factor: the line n rows from the current one is drawn at
#: ``fade ** n`` opacity. Range and default from the Reader C prototype.
FADE_PER_LINE_MIN = 0.2
FADE_PER_LINE_MAX = 0.95
_FADE_PER_LINE_DEFAULT = 0.6

#: How a mistyped character is marked on the reading surface. Chosen by the
#: user against the Reader C prototype; "tint" (colour the glyph itself red)
#: is the default because it was the least visually noisy of the options
#: tried.
ERROR_STYLES = ("tint", "underline", "dot", "strike", "wavy")
_ERROR_STYLE_DEFAULT = "tint"


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


def _clamp_font_family(value) -> str:
    """Fall back to the default rather than reject -- same defence-in-depth as
    the rest of ``from_dict``; the strict reject-on-unknown-value lives in
    ``POST /api/settings``."""
    return value if value in FONT_FAMILIES else _FONT_FAMILY_DEFAULT


def _clamp_font_size_px(value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = _FONT_SIZE_PX_DEFAULT
    return min(max(value, FONT_SIZE_PX_MIN), FONT_SIZE_PX_MAX)


def _clamp_visible_lines(value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = _VISIBLE_LINES_DEFAULT
    value = min(max(value, VISIBLE_LINES_MIN), VISIBLE_LINES_MAX)
    if value % 2 == 0:
        value += 1
        # rounding up may have pushed an even VISIBLE_LINES_MAX past the
        # ceiling -- fall back to one below it, which is odd by construction
        # since VISIBLE_LINES_MAX was even.
        if value > VISIBLE_LINES_MAX:
            value -= 2
    return value


def _clamp_fade_per_line(value) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = _FADE_PER_LINE_DEFAULT
    return min(max(value, FADE_PER_LINE_MIN), FADE_PER_LINE_MAX)


def _clamp_error_style(value) -> str:
    return value if value in ERROR_STYLES else _ERROR_STYLE_DEFAULT


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
    # Added 2026-09-20 for the reading-surface refresh (docs/mockups/
    # UI_Mockup_Reader_C.html, the agreed design): face, size, how many lines
    # show at once, how fast the off-line lines fade, and how an error is
    # marked. All five live in the drawer's "Advanced" settings section, not
    # on the typing surface itself. Defaults and bounds were chosen by the
    # user against the live prototype -- see the module constants above for
    # each one's range and do not "improve" them without going back there.
    font_family: str = _FONT_FAMILY_DEFAULT
    font_size_px: int = _FONT_SIZE_PX_DEFAULT
    visible_lines: int = _VISIBLE_LINES_DEFAULT
    fade_per_line: float = _FADE_PER_LINE_DEFAULT
    error_style: str = _ERROR_STYLE_DEFAULT

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
            font_family=_clamp_font_family(data.get("font_family", defaults.font_family)),
            font_size_px=_clamp_font_size_px(data.get("font_size_px", defaults.font_size_px)),
            visible_lines=_clamp_visible_lines(data.get("visible_lines", defaults.visible_lines)),
            fade_per_line=_clamp_fade_per_line(data.get("fade_per_line", defaults.fade_per_line)),
            error_style=_clamp_error_style(data.get("error_style", defaults.error_style)),
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
