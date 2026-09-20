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
    user            TEXT,
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
    user      TEXT NOT NULL,
    text_name TEXT NOT NULL,
    line      INTEGER NOT NULL,
    PRIMARY KEY (user, text_name)
);

CREATE TABLE IF NOT EXISTS users (
    name      TEXT PRIMARY KEY,
    created   TEXT,
    anonymous INTEGER NOT NULL DEFAULT 0
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
    # After the column exists, never inside SCHEMA: executescript runs before
    # the additive migration, so an index on a new column fails on an existing
    # database with "no such column".
    conn.execute("CREATE INDEX IF NOT EXISTS attempts_user ON attempts (user)")
    _migrate_positions_to_per_user(conn, LEGACY_OWNER)
    _adopt_legacy_rows(conn, LEGACY_OWNER)
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
    # 2026-09-20: whose attempt this was. Everything before multi-user belongs
    # to one person, and _adopt_legacy_rows below assigns it rather than
    # leaving it orphaned under NULL.
    "attempts": {"user": "TEXT"},
}


#: Everything recorded before the tool knew about users belongs to one person.
#: Named rather than left as NULL so every query can assume a user, and chosen
#: by the person whose history it actually is (JC, 2026-09-20).
LEGACY_OWNER = "James"

#: A browser with no remembered name gets one of these. They are ordinary users
#: in every respect; the flag only drives the "save progress as..." prompt.
GUEST_PREFIX = "Guest "


def active_user() -> str:
    """Whose data the unqualified read/write helpers operate on.

    A module-level active user rather than a parameter on forty call sites:
    one process serves one person at a time (one Session per server), and
    analysis, drills and the review all read "the current user's history"
    without wanting to know that users exist. The server sets it when the
    browser says who it is; everything else inherits it.
    """
    return _ACTIVE["user"]


def set_active_user(name: str) -> str:
    _ACTIVE["user"] = name
    return name


_ACTIVE = {"user": LEGACY_OWNER}


def _migrate_positions_to_per_user(conn: sqlite3.Connection, owner: str) -> int:
    """Rebuild `positions` with (user, text_name) as its key.

    SQLite cannot alter a primary key, so the table is rebuilt and its rows
    carried across under ``owner``. Done inside the caller's transaction: a
    half-migrated positions table would lose the reader's place in the book,
    which is the one thing this application must never do.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(positions)")}
    if not columns or "user" in columns:
        return 0
    rows = conn.execute("SELECT text_name, line FROM positions").fetchall()
    conn.execute("ALTER TABLE positions RENAME TO positions_pre_users")
    conn.execute(
        "CREATE TABLE positions ("
        " user TEXT NOT NULL, text_name TEXT NOT NULL, line INTEGER NOT NULL,"
        " PRIMARY KEY (user, text_name))"
    )
    for row in rows:
        conn.execute(
            "INSERT INTO positions (user, text_name, line) VALUES (?, ?, ?)",
            (owner, row["text_name"], row["line"]),
        )
    moved = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    if moved != len(rows):
        raise RuntimeError(
            f"positions migration moved {moved} of {len(rows)} rows; refusing to "
            "drop the original, which is still at positions_pre_users"
        )
    conn.execute("DROP TABLE positions_pre_users")
    return moved


def _adopt_legacy_rows(conn: sqlite3.Connection, owner: str) -> int:
    """Give every pre-multi-user attempt to ``owner`` and register the users."""
    adopted = conn.execute(
        "UPDATE attempts SET user = ? WHERE user IS NULL", (owner,)
    ).rowcount
    for (name,) in conn.execute(
        "SELECT DISTINCT user FROM attempts WHERE user IS NOT NULL"
    ).fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO users (name, created, anonymous) VALUES (?, ?, 0)",
            (name, datetime.now().isoformat(timespec="seconds")),
        )
    for (name,) in conn.execute("SELECT DISTINCT user FROM positions").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO users (name, created, anonymous) VALUES (?, ?, 0)",
            (name, datetime.now().isoformat(timespec="seconds")),
        )
    return adopted


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
            _insert_attempt(conn, key, record, None, LEGACY_OWNER)
            moved["attempts"] += 1

    if positions_path().exists():
        try:
            positions = json.loads(positions_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            positions = {}
        for text_name, line in positions.items():
            conn.execute(
                "INSERT OR REPLACE INTO positions (user, text_name, line)"
                " VALUES (?, ?, ?)",
                (LEGACY_OWNER, text_name, int(line)),
            )
            moved["positions"] += 1

    conn.commit()
    return moved


def _insert_attempt(conn, key, record, keystrokes, user=None) -> int:
    known = {col: record.get(field) for field, col in _COLUMNS.items()}
    if known.get("passed") is not None:
        known["passed"] = int(bool(known["passed"]))
    extra = {k: v for k, v in record.items() if k not in _COLUMNS}
    cols = ["key"] + list(known) + ["user", "extra"]
    values = (
        [key] + list(known.values()) + [user, json.dumps(extra) if extra else None]
    )
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


def append_attempt(record: dict, key: str | None = None, keystrokes=None, user=None) -> str:
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
        _insert_attempt(conn, key, record, keystrokes, user or active_user())
        conn.commit()
        return key
    finally:
        conn.close()


def clear_history(text_name: str | None = None, user=None) -> None:
    """Clear the current user's attempts, or only those for one text.

    Scoped to one user: clearing your own history must never touch anyone
    else's. Keystrokes go with the attempts they belong to.
    """
    who = user or active_user()
    conn = connect()
    try:
        if text_name is None:
            conn.execute(
                "DELETE FROM keystrokes WHERE attempt_id IN"
                " (SELECT id FROM attempts WHERE user = ?)",
                (who,),
            )
            conn.execute("DELETE FROM attempts WHERE user = ?", (who,))
        else:
            conn.execute(
                "DELETE FROM keystrokes WHERE attempt_id IN"
                " (SELECT id FROM attempts WHERE text_name = ? AND user = ?)",
                (text_name, who),
            )
            conn.execute(
                "DELETE FROM attempts WHERE text_name = ? AND user = ?",
                (text_name, who),
            )
        conn.commit()
    finally:
        conn.close()


def set_position(text_name: str, line: int, user=None) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO positions (user, text_name, line) VALUES (?, ?, ?)"
            " ON CONFLICT (user, text_name) DO UPDATE SET line = excluded.line",
            (user or active_user(), text_name, int(line)),
        )
        conn.commit()
    finally:
        conn.close()


# ---- reading ---------------------------------------------------------------


def read_attempts(user=None) -> dict:
    """Every attempt, keyed by timestamp, in the shape the JSON store used.

    Kept because the rest of the code already speaks this shape. New code that
    cares about order or size should use ``iter_attempts``.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM attempts WHERE user = ? ORDER BY key", (user or active_user(),)
        ).fetchall()
        return {row["key"]: _row_to_record(row) for row in rows}
    finally:
        conn.close()


def iter_attempts(text_name: str | None = None, limit: int | None = None, user=None) -> list:
    """Attempts oldest first as ``(key, record)`` pairs, optionally one text only."""
    conn = connect()
    try:
        sql = "SELECT * FROM attempts WHERE user = ?"
        args = [user or active_user()]
        if text_name is not None:
            sql += " AND text_name = ?"
            args.append(text_name)
        sql += " ORDER BY key"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(int(limit))
        return [(row["key"], _row_to_record(row)) for row in conn.execute(sql, args)]
    finally:
        conn.close()


def read_keystrokes(key: str, user=None) -> list:
    """The keystrokes of one attempt, in order. Empty when it was not instrumented."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT k.seq, k.char, k.expected, k.ms, k.correct FROM keystrokes k"
            " JOIN attempts a ON a.id = k.attempt_id"
            " WHERE a.key = ? AND a.user = ? ORDER BY k.seq",
            (key, user or active_user()),
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


def iter_keystroke_attempts(text_name: str | None = None, user=None) -> list:
    """Every instrumented attempt as ``(key, record, keystrokes)``.

    One query for all the keystrokes rather than one per attempt: the speed
    analysis reads the whole history, and per-attempt queries were the slow way.
    """
    conn = connect()
    try:
        sql = "SELECT * FROM attempts WHERE user = ?"
        args = [user or active_user()]
        if text_name is not None:
            sql += " AND text_name = ?"
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


def read_positions(user=None) -> dict:
    conn = connect()
    try:
        return {
            row["text_name"]: row["line"]
            for row in conn.execute(
                "SELECT text_name, line FROM positions WHERE user = ?",
                (user or active_user(),),
            )
        }
    finally:
        conn.close()


def get_position(text_name: str, default: int = 0, user=None) -> int:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT line FROM positions WHERE text_name = ? AND user = ?",
            (text_name, user or active_user()),
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


# ---- users -----------------------------------------------------------------


def list_users() -> list:
    """Every known user, most recently active first.

    Each entry carries enough for a picker to be useful without a second
    query: how many attempts they have, when they were last at it, and how
    far through their current text they are.
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT u.name, u.anonymous,"
            "       (SELECT COUNT(*) FROM attempts a WHERE a.user = u.name) AS attempts,"
            "       (SELECT MAX(a.key) FROM attempts a WHERE a.user = u.name) AS last_active,"
            "       (SELECT MAX(p.line) FROM positions p WHERE p.user = u.name) AS line"
            " FROM users u"
        ).fetchall()
        out = [
            {
                "name": r["name"],
                "anonymous": bool(r["anonymous"]),
                "attempts": r["attempts"],
                "last_active": r["last_active"],
                "line": r["line"],
            }
            for r in rows
        ]
        out.sort(key=lambda u: (u["last_active"] or "", u["attempts"]), reverse=True)
        return out
    finally:
        conn.close()


def ensure_user(name: str, anonymous: bool = False) -> str:
    """Register ``name`` if it is new, and return it. Idempotent."""
    conn = connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO users (name, created, anonymous) VALUES (?, ?, ?)",
            (name, datetime.now().isoformat(timespec="seconds"), int(bool(anonymous))),
        )
        conn.commit()
        return name
    finally:
        conn.close()


def user_exists(name: str) -> bool:
    conn = connect()
    try:
        return (
            conn.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone()
            is not None
        )
    finally:
        conn.close()


def is_anonymous(name: str) -> bool:
    """Whether ``name`` is a guest the tool minted rather than one someone chose.

    A stored flag, not a pattern on the name: "Guest 7" is a perfectly legal
    thing for a person to call themselves, and the page decides whether to
    offer "save progress as..." from this.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT anonymous FROM users WHERE name = ?", (name,)
        ).fetchone()
        return bool(row["anonymous"]) if row else False
    finally:
        conn.close()


def next_guest_name() -> str:
    """``Guest 1``, ``Guest 2``, ... -- the first number not already taken.

    A browser that has never been here gets one of these and starts typing
    immediately; nothing blocks on being asked who you are.
    """
    existing = {u["name"] for u in list_users()}
    n = 1
    while f"{GUEST_PREFIX}{n}" in existing:
        n += 1
    return f"{GUEST_PREFIX}{n}"


def rename_user(old: str, new: str) -> dict:
    """Move every trace of ``old`` to ``new``, in one transaction.

    This is how a guest keeps the progress they have already made when they
    finally give a name. It refuses to write into a name that already exists:
    merging two people's histories silently would be unrecoverable, and there
    is no way to tell from here whether that is what was meant.
    """
    if user_exists(new):
        raise ValueError(f"{new} already exists; choose another name")
    conn = connect()
    try:
        conn.execute("BEGIN")
        moved = conn.execute(
            "UPDATE attempts SET user = ? WHERE user = ?", (new, old)
        ).rowcount
        positions = conn.execute(
            "UPDATE positions SET user = ? WHERE user = ?", (new, old)
        ).rowcount
        conn.execute(
            "INSERT OR IGNORE INTO users (name, created, anonymous) VALUES (?, ?, 0)",
            (new, datetime.now().isoformat(timespec="seconds")),
        )
        conn.execute("UPDATE users SET anonymous = 0 WHERE name = ?", (new,))
        conn.execute("DELETE FROM users WHERE name = ?", (old,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if active_user() == old:
        set_active_user(new)
    return {"attempts": moved, "positions": positions, "from": old, "to": new}
