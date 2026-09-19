"""history.py -- the attempt store: past typing attempts, their keystrokes, and per-text positions.

SQLite, at ``state_dir()/history.db``. Written 2026-09-19 for the UI refresh
(docs/UI_Refresh_Notes.md), replacing the two JSON files this module used before,
which in turn replaced the original pickle. Both older formats migrate in
automatically and are left on disk untouched; see ``import_legacy_json``.

Why a database. Every attempt now carries its keystrokes -- roughly a hundred rows
of ``(char, expected, ms, correct)`` per line -- because per-key and bigram
latency, and the mistakes a retyped line hides, are what
actually identifies a weak point, and that cannot be reconstructed afterwards. A
JSON file rewritten in full on every line does not survive that; ten thousand lines
of keystrokes is tens of megabytes read and written per attempt.

Record field names are unchanged from the JSON era (EventTime, TextName, Length,
Duration, Accuracy, Wpm, Answer, user_input, user_input_full), so migrated and
freshly recorded attempts are one dataset rather than two shapes. Records written
before the refactor keep their quirks: some carry an unformatted EventTime and no
Length. Nothing here normalises them.

Verified by tests/test_history.py.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3

from . import paths

#: Columns promoted out of the record dict into real columns. Anything else in a
#: record is preserved verbatim in the ``extra`` JSON blob, so an old record with a
#: field nobody remembers is never silently dropped.
_COLUMNS = {
    "EventTime": "event_time",
    "TextName": "text_name",
    "Length": "length",
    "Duration": "duration",
    "Accuracy": "accuracy",
    "Wpm": "wpm",
    "Answer": "answer",
    "user_input": "user_input",
    "user_input_full": "user_input_full",
    "Passed": "passed",
    "LineIndex": "line_index",
}
_REVERSE = {v: k for k, v in _COLUMNS.items()}

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id              INTEGER PRIMARY KEY,
    key             TEXT    NOT NULL UNIQUE,
    event_time      TEXT,
    text_name       TEXT,
    line_index      INTEGER,
    length          INTEGER,
    duration        REAL,
    accuracy        REAL,
    wpm             REAL,
    passed          INTEGER,
    answer          TEXT,
    user_input      TEXT,
    user_input_full TEXT,
    extra           TEXT
);
CREATE INDEX IF NOT EXISTS attempts_text ON attempts (text_name);

CREATE TABLE IF NOT EXISTS keystrokes (
    attempt_id INTEGER NOT NULL REFERENCES attempts (id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    char       TEXT,
    expected   TEXT,
    ms         REAL,
    correct    INTEGER,
    PRIMARY KEY (attempt_id, seq)
);

CREATE TABLE IF NOT EXISTS positions (
    text_name TEXT PRIMARY KEY,
    line      INTEGER NOT NULL
);
"""


def db_path() -> Path:
    return paths.state_dir() / "history.db"


def history_path() -> Path:
    """The pre-SQLite attempt file. Kept only so the importer can find it."""
    return paths.state_dir() / "history.json"


def positions_path() -> Path:
    """The pre-SQLite positions file. Kept only so the importer can find it."""
    return paths.state_dir() / "positions.json"


def connect() -> sqlite3.Connection:
    """Open the database, creating and importing legacy JSON on first use.

    Lazy creation is the rule for everything under ``paths``; this is the same
    thing one level down. Callers close the connection they are given.
    """
    first_time = not db_path().exists()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    conn.commit()
    if first_time:
        import_legacy_json(conn)
    return conn


#: Columns added to an existing table after it shipped. ``CREATE TABLE IF NOT
#: EXISTS`` does nothing to a table that already exists, so a database created
#: before a column was introduced needs it added explicitly. Additive only:
#: SQLite cannot drop a column without rebuilding the table, and nothing here
#: is allowed to rewrite a user's history.
_ADDED_COLUMNS = {
    # 2026-09-19: what the typist was supposed to press. Recorded because the
    # expected character cannot be reconstructed afterwards -- backspaces are
    # deliberately not recorded, so the position at any given press is
    # ambiguous -- and because with a 99% accuracy floor the submitted text is
    # almost always perfect, so the mistakes only exist in the keystrokes.
    "keystrokes": {"expected": "TEXT"},
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def import_legacy_json(conn: sqlite3.Connection) -> dict:
    """Pull an older history.json / positions.json into an empty database.

    Runs once, when the database is created, so upgrading the tool does not look
    like losing your history. The JSON files are read and left exactly where they
    are: this is a copy, and deleting the originals is the user's call.
    """
    moved = {"attempts": 0, "positions": 0}
    if conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]:
        return moved

    if history_path().exists():
        try:
            attempts = json.loads(history_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            attempts = {}
        for key, record in attempts.items():
            _insert_attempt(conn, key, record, None)
            moved["attempts"] += 1

    if positions_path().exists():
        try:
            positions = json.loads(positions_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            positions = {}
        for text_name, line in positions.items():
            conn.execute(
                "INSERT OR REPLACE INTO positions (text_name, line) VALUES (?, ?)",
                (text_name, int(line)),
            )
            moved["positions"] += 1

    conn.commit()
    return moved


def _insert_attempt(conn, key, record, keystrokes) -> int:
    known = {col: record.get(field) for field, col in _COLUMNS.items()}
    if known.get("passed") is not None:
        known["passed"] = int(bool(known["passed"]))
    extra = {k: v for k, v in record.items() if k not in _COLUMNS}
    cols = ["key"] + list(known) + ["extra"]
    values = [key] + list(known.values()) + [json.dumps(extra) if extra else None]
    placeholders = ", ".join("?" * len(cols))
    cur = conn.execute(
        f"INSERT INTO attempts ({', '.join(cols)}) VALUES ({placeholders})", values
    )
    attempt_id = cur.lastrowid
    if keystrokes:
        conn.executemany(
            "INSERT INTO keystrokes (attempt_id, seq, char, expected, ms, correct)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    attempt_id,
                    seq,
                    k.get("char"),
                    k.get("expected"),
                    float(k.get("ms", 0.0)),
                    None if k.get("correct") is None else int(bool(k.get("correct"))),
                )
                for seq, k in enumerate(keystrokes)
            ],
        )
    return attempt_id


def _row_to_record(row: sqlite3.Row) -> dict:
    record = {}
    for col, field in _REVERSE.items():
        value = row[col]
        if value is None:
            continue
        if field == "Passed":
            value = bool(value)
        record[field] = value
    if row["extra"]:
        record.update(json.loads(row["extra"]))
    return record


# ---- writing ---------------------------------------------------------------


def append_attempt(record: dict, key: str | None = None, keystrokes=None) -> str:
    """Add one attempt and return the key it was stored under.

    ``keystrokes`` is a list of ``{"char", "expected", "ms", "correct"}`` in
    the order they were pressed, ``ms`` measured from the first keypress of the
    line. It may be omitted: attempts recorded before instrumentation, and the
    migrated ones, simply have none, and every analysis that needs timing skips
    them rather than guessing.
    """
    conn = connect()
    try:
        if key is None:
            key = datetime.now().isoformat()
            while conn.execute("SELECT 1 FROM attempts WHERE key = ?", (key,)).fetchone():
                key = datetime.now().isoformat()
        _insert_attempt(conn, key, record, keystrokes)
        conn.commit()
        return key
    finally:
        conn.close()


def clear_history(text_name: str | None = None) -> None:
    """Clear all attempts, or only those for one text. Keystrokes go with them."""
    conn = connect()
    try:
        if text_name is None:
            conn.execute("DELETE FROM keystrokes")
            conn.execute("DELETE FROM attempts")
        else:
            conn.execute(
                "DELETE FROM keystrokes WHERE attempt_id IN"
                " (SELECT id FROM attempts WHERE text_name = ?)",
                (text_name,),
            )
            conn.execute("DELETE FROM attempts WHERE text_name = ?", (text_name,))
        conn.commit()
    finally:
        conn.close()


def set_position(text_name: str, line: int) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO positions (text_name, line) VALUES (?, ?)"
            " ON CONFLICT (text_name) DO UPDATE SET line = excluded.line",
            (text_name, int(line)),
        )
        conn.commit()
    finally:
        conn.close()


# ---- reading ---------------------------------------------------------------


def read_attempts() -> dict:
    """Every attempt, keyed by timestamp, in the shape the JSON store used.

    Kept because the rest of the code already speaks this shape. New code that
    cares about order or size should use ``iter_attempts``.
    """
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM attempts ORDER BY key").fetchall()
        return {row["key"]: _row_to_record(row) for row in rows}
    finally:
        conn.close()


def iter_attempts(text_name: str | None = None, limit: int | None = None) -> list:
    """Attempts oldest first as ``(key, record)`` pairs, optionally one text only."""
    conn = connect()
    try:
        sql = "SELECT * FROM attempts"
        args = []
        if text_name is not None:
            sql += " WHERE text_name = ?"
            args.append(text_name)
        sql += " ORDER BY key"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(int(limit))
        return [(row["key"], _row_to_record(row)) for row in conn.execute(sql, args)]
    finally:
        conn.close()


def read_keystrokes(key: str) -> list:
    """The keystrokes of one attempt, in order. Empty when it was not instrumented."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT k.seq, k.char, k.expected, k.ms, k.correct FROM keystrokes k"
            " JOIN attempts a ON a.id = k.attempt_id WHERE a.key = ? ORDER BY k.seq",
            (key,),
        ).fetchall()
        return [
            {
                "char": row["char"],
                "expected": row["expected"],
                "ms": row["ms"],
                "correct": None if row["correct"] is None else bool(row["correct"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def iter_keystroke_attempts(text_name: str | None = None) -> list:
    """Every instrumented attempt as ``(key, record, keystrokes)``.

    One query for all the keystrokes rather than one per attempt: the speed
    analysis reads the whole history, and per-attempt queries were the slow way.
    """
    conn = connect()
    try:
        sql = "SELECT * FROM attempts"
        args = []
        if text_name is not None:
            sql += " WHERE text_name = ?"
            args.append(text_name)
        sql += " ORDER BY key"
        attempts = {
            row["id"]: (row["key"], _row_to_record(row)) for row in conn.execute(sql, args)
        }
        strokes = {aid: [] for aid in attempts}
        for row in conn.execute(
            "SELECT attempt_id, char, expected, ms, correct FROM keystrokes"
            " ORDER BY attempt_id, seq"
        ):
            if row["attempt_id"] in strokes:
                strokes[row["attempt_id"]].append(
                    {
                        "char": row["char"],
                        "expected": row["expected"],
                        "ms": row["ms"],
                        "correct": None if row["correct"] is None else bool(row["correct"]),
                    }
                )
        return [
            (key, record, strokes[aid])
            for aid, (key, record) in attempts.items()
            if strokes[aid]
        ]
    finally:
        conn.close()


def read_positions() -> dict:
    conn = connect()
    try:
        return {
            row["text_name"]: row["line"]
            for row in conn.execute("SELECT text_name, line FROM positions")
        }
    finally:
        conn.close()


def get_position(text_name: str, default: int = 0) -> int:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT line FROM positions WHERE text_name = ?", (text_name,)
        ).fetchone()
        return int(row["line"]) if row else default
    finally:
        conn.close()


def stats() -> dict:
    """Row counts, for `pixi run where` and the migration report."""
    conn = connect()
    try:
        return {
            "attempts": conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],
            "keystrokes": conn.execute("SELECT COUNT(*) FROM keystrokes").fetchone()[0],
            "instrumented": conn.execute(
                "SELECT COUNT(DISTINCT attempt_id) FROM keystrokes"
            ).fetchone()[0],
            "positions": conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0],
        }
    finally:
        conn.close()
