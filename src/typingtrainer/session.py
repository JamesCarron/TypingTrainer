"""The headless typing game.

Everything that used to live in ``Game`` in the old flat ``TypingTrainer.py``
except the widgets: the READY/GAME state machine, the text library, scoring an
attempt, advancing on a pass, and persisting position, history and settings.

Nothing here may import tkinter, open a socket, print, or read the clock.
``submit_line`` is handed the duration rather than measuring it, which is what
lets the browser, the desktop app and the tests all drive the same engine.

Written 2026-09-19 during the refactor described in docs/Refactor_Plan.md; the
public surface is fixed by docs/Contracts.md. Verified by tests/test_session.py.
"""

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
import shutil

from . import config, history, paths
from .scoring import passing_grade, typing_score
from .texts import Text

#: The sample that ships inside the package. The display name is pinned rather
#: than derived from the filename because the saved position and every one of
#: the migrated history records is keyed by it.
BUNDLED_DIR = Path(__file__).parent / "texts_bundled"
BUNDLED_NAMES = {"artofwar.txt": "Art of War"}

VALID_STATES = ("READY", "GAME")


@dataclass(frozen=True)
class AttemptResult:
    """One scored line. ``position`` is where the player is *after* the attempt."""

    target: str
    typed: str
    matches: list
    accuracy: float
    wpm: float
    duration: float
    passed: bool
    position: int

    def as_dict(self) -> dict:
        return asdict(self)


class TextNotFound(LookupError):
    """Asked for a text that is in neither the bundled set nor the user library."""


def available_texts() -> dict:
    """``{display name: (path to the folder, filename, source)}`` over both sources.

    A user text whose name collides with a bundled one wins, so a local copy can
    override the sample without renaming it.
    """
    found = {}
    for f in sorted(BUNDLED_DIR.glob("*.txt")):
        found[BUNDLED_NAMES.get(f.name, f.stem)] = (BUNDLED_DIR, f.name, "bundled")
    library = paths.texts_dir()
    for f in sorted(library.glob("*.txt")):
        found[BUNDLED_NAMES.get(f.name, f.stem)] = (library, f.name, "library")
    return found


class Session:
    """One player working through one text."""

    def __init__(self, settings=None, text_name=None, display_lines=5):
        self.settings = settings if settings is not None else config.load()
        self.display_lines = display_lines
        self.state = "READY"
        self.last_result = None
        self._text = None
        #: Set by ``start_drill`` to the drill line currently being typed, else
        #: None. See ``start_drill`` for why this exists and how small the
        #: change is kept.
        self._drill_line = None
        self.select_text(text_name or self._default_text_name())

    # ---- text library -----------------------------------------------------

    def _default_text_name(self) -> str:
        """The text the player was last on, else the first one available."""
        names = list(available_texts())
        for name in history.read_positions():
            if name in names:
                return name
        if not names:
            raise TextNotFound("no texts are available at all")
        return names[0]

    def select_text(self, name: str) -> None:
        """Switch text, restoring that text's saved position."""
        library = available_texts()
        if name not in library:
            raise TextNotFound(name)
        folder, filename, _source = library[name]
        text = Text(name, filename)
        text.load(folder)
        text.position = min(max(history.get_position(name, 0), 0), max(len(text), 0))
        self._text = text
        self.last_result = None
        self._drill_line = None
        self.set_state("READY")

    def add_text(self, source_path) -> str:
        """Copy a .txt into the user's library and return its display name.

        Copied rather than referenced in place: a text is re-read every session,
        so a path into someone's Downloads folder breaks quietly a week later.
        """
        source = Path(source_path)
        if source.suffix.lower() != ".txt":
            raise ValueError(f"not a .txt file: {source.name}")
        if not source.is_file():
            raise FileNotFoundError(source)
        target = paths.texts_dir() / source.name
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        return BUNDLED_NAMES.get(target.name, target.stem)

    # ---- who is playing ----------------------------------------------------

    @property
    def user(self) -> str:
        return history.active_user()

    def switch_user(self, name: str) -> str:
        """Make ``name`` the active user and reload their place in the book.

        Everything the store reads is scoped to the active user, so switching
        is: register them, make them active, then re-select the current text,
        which is what pulls their saved position rather than the last person's.
        """
        history.ensure_user(name)
        history.set_active_user(name)
        self.select_text(self.text_name)
        return name

    # ---- where the player is ----------------------------------------------

    @property
    def text_name(self) -> str:
        return self._text.name

    @property
    def position(self) -> int:
        return self._text.position

    @property
    def line_count(self) -> int:
        return len(self._text)

    @property
    def progress(self) -> float:
        return self._text.position / self.line_count if self.line_count else 0.0

    def current_line(self) -> str:
        """The line to type now; empty string past the end rather than an IndexError.

        A drill in progress (``start_drill``) overrides this unconditionally --
        the book position underneath is untouched, it is just not what the
        player is typing for the duration of the drill attempt.
        """
        if self._drill_line is not None:
            return self._drill_line
        if 0 <= self._text.position < self.line_count:
            return self._text.contents[self._text.position]
        return ""

    def visible_lines(self, n=None) -> list:
        n = self.display_lines if n is None else n
        start = self._text.position
        return list(self._text.contents[start : start + n])

    def preceding_lines(self, n=7) -> list:
        """The up-to-``n`` lines before the current one, in reading order.

        Added 2026-09-20 for the reading surface, which shows the book above
        the current line as well as below it. Without this the view could only
        fill downwards and the page sat lop-sided; the page must not invent the
        text above, because nothing else would hold it (docs/Contracts.md: no
        state in the view that the engine does not also have). Fewer than ``n``
        lines come back near the start of a text, which is correct -- there is
        genuinely nothing before line zero.
        """
        start = max(0, self._text.position - n)
        return list(self._text.contents[start : self._text.position])

    # ---- state machine -----------------------------------------------------

    def set_state(self, new_state: str) -> None:
        if new_state not in VALID_STATES:
            raise ValueError(f"Tried to set invalid GameState: {new_state}")
        self.state = new_state

    def start(self) -> None:
        """READY -> GAME."""
        self.set_state("GAME")

    def abort(self) -> None:
        """GAME -> READY, discarding the attempt without logging it (the Esc path).

        Also cancels a drill in progress, if any -- an abandoned drill is not
        logged (nothing was submitted) and must not leave the session stuck
        typing a line that is not in the book.
        """
        self._drill_line = None
        self.set_state("READY")

    def start_drill(self, line: str) -> None:
        """Make ``line`` the target for exactly one attempt, without touching the book.

        Added 2026-09-19 for the improvement loop (docs/UI_Refresh_Notes.md,
        Proposal C, "Turning analysis into improvement"): a drill line from
        ``drills.generate_drill``, or a hard line from ``drills.find_hard_line``
        that the player wants to rehearse before it is reached, needs a target
        that is not a step through the book -- typing it must never move
        ``self._text.position`` or call ``history.set_position``, and it must
        not linger past one submitted attempt.

        This is the smallest change that gets there: one optional override
        (``self._drill_line``), consulted by ``current_line()`` in place of the
        book's current line, and cleared unconditionally -- pass or fail -- at
        the end of ``submit_line`` once that one attempt has been scored. No
        second state, no stack, no change to ``visible_lines`` or the book
        position at all. ``submit_line`` marks the logged record
        ``"Drill": True`` instead of advancing position, so a drill attempt is
        indistinguishable from a book attempt everywhere except that one field.

        Puts the session in GAME (the drill is typed immediately), which also
        means calling this while a book line is mid-attempt discards that
        attempt the same way ``abort()`` would -- there is only ever one
        current target.
        """
        if not isinstance(line, str) or not line.strip():
            raise ValueError("drill line must be a non-empty string")
        self._drill_line = line
        self.last_result = None
        self.set_state("GAME")

    # ---- the scoring path --------------------------------------------------

    def submit_line(
        self, typed: str, duration: float, typed_full=None, when=None, keystrokes=None
    ) -> AttemptResult:
        """Score one line, log it, advance on a pass, and persist.

        ``typed_full`` is the raw keystroke record including characters that were
        later deleted, kept because the old history recorded it. ``when`` is the
        attempt's start time, supplied by the caller for the same reason the
        duration is: the engine does not read the clock.

        ``keystrokes`` is the instrumentation added 2026-09-19: a list of
        ``{"char", "ms", "correct"}`` in press order, ``ms`` from the first key of
        the line. It is what makes per-key and bigram latency possible, and it
        cannot be reconstructed later, so a view that can capture it should. A
        view that cannot simply omits it.
        """
        if self.state != "GAME":
            raise RuntimeError(f"submit_line is only legal in GAME, not {self.state}")
        target = self.current_line()
        is_drill = self._drill_line is not None
        scored = typing_score(typed, target, duration)
        passed = passing_grade(
            scored,
            require_accuracy=self.settings.require_accuracy,
            min_accuracy=self.settings.min_accuracy,
            require_wpm=self.settings.require_wpm,
            min_wpm=self.settings.min_wpm,
        )
        started = when or datetime.now()
        record = {
            "EventTime": f"{started:%d-%m-%Y %H:%M:%S}",
            "TextName": self.text_name,
            "Length": len(target),
            "Duration": scored["duration"],
            "Accuracy": scored["accuracy"],
            "Wpm": scored["wpm"],
            "Answer": target,
            "user_input": typed,
            "user_input_full": typed_full if typed_full is not None else typed,
            "Passed": passed,
            "LineIndex": self._text.position,
        }
        # Marked rather than folded into TextName, so a drill is a real,
        # analysable attempt but never confused with a book line -- see
        # start_drill's docstring.
        if is_drill:
            record["Drill"] = True
        history.append_attempt(
            record,
            key=started.isoformat(),
            keystrokes=keystrokes,
        )
        # A drill never advances the book position, pass or fail -- it is
        # practice, not progress through the text.
        if passed and not is_drill:
            self._text.position += 1
            history.set_position(self.text_name, self._text.position)
        result = AttemptResult(
            target=target,
            typed=typed,
            matches=scored["matches"],
            accuracy=scored["accuracy"],
            wpm=scored["wpm"],
            duration=scored["duration"],
            passed=passed,
            position=self._text.position,
        )
        self.last_result = result
        # One attempt is the whole life of a drill -- clear it unconditionally
        # so the very next current_line() is back to the book, right where it
        # was.
        if is_drill:
            self._drill_line = None
        return result

    # ---- moving about ------------------------------------------------------

    def change_position(self, delta: int) -> None:
        self._set_position(self._text.position + delta)

    def jump_to(self, line_number: int) -> None:
        """``line_number`` is 1-based, as the position label shows it."""
        self._set_position(line_number - 1)

    def _set_position(self, index: int) -> None:
        self._text.position = min(max(index, 0), max(self.line_count - 1, 0))
        history.set_position(self.text_name, self._text.position)
        self.last_result = None
        self.set_state("READY")

    # ---- settings and history ----------------------------------------------

    def update_settings(self, **kwargs):
        unknown = set(kwargs) - set(vars(self.settings))
        if unknown:
            raise ValueError(f"unknown setting(s): {', '.join(sorted(unknown))}")
        if "min_accuracy" in kwargs:
            kwargs["min_accuracy"] = min(max(float(kwargs["min_accuracy"]), 0.0), 1.0)
        if "min_wpm" in kwargs:
            kwargs["min_wpm"] = max(0.0, float(kwargs["min_wpm"]))
        for flag in ("require_accuracy", "require_wpm", "show_criteria", "flash_on_mistake"):
            if flag in kwargs:
                kwargs[flag] = bool(kwargs[flag])
        self.settings = replace(self.settings, **kwargs)
        config.save(self.settings)
        return self.settings

    def reset_history(self, scope="current") -> int:
        """Clear history for the current text or all of it; returns records removed."""
        if scope not in ("current", "all"):
            raise ValueError(f"unknown scope: {scope}")
        before = len(history.read_attempts())
        history.clear_history(None if scope == "all" else self.text_name)
        return before - len(history.read_attempts())

    # ---- what a view needs -------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "user": self.user,
            "user_is_guest": history.is_anonymous(self.user),
            "state": self.state,
            "text_name": self.text_name,
            "position": self.position,
            "line_count": self.line_count,
            "progress": self.progress,
            "visible_lines": self.visible_lines(),
            "previous_lines": self.preceding_lines(),
            "current_line": self.current_line(),
            "in_drill": self._drill_line is not None,
            "drill_line": self._drill_line,
            "settings": asdict(self.settings),
            "texts": [
                {"name": name, "source": source}
                for name, (_folder, _file, source) in available_texts().items()
            ],
            "last_result": self.last_result.as_dict() if self.last_result else None,
        }
