"""paths.py -- the only module that knows where TypingTrainer keeps its data.

Written 2026-09-19 for the "Paths and migration" stream of the repo's stage 4 refactor
(see docs/Refactor_Plan.md). Nothing else in the package hard-codes a path; everything
calls one of these. Verified by tests/test_paths.py (TYPINGTRAINER_HOME redirection,
folder auto-creation, and display() never raising).

TypingTrainer is a personal public GitHub project, not an Auterion tool, so unlike the
house `new-project` template this carries no vendor folder in its data roots:

* ``state_dir()``      %LOCALAPPDATA%\\TypingTrainer\\             settings, history, positions
* ``cache_dir()``      %LOCALAPPDATA%\\TypingTrainer\\Cache\\      reserved, nothing lives here yet
* ``documents_dir()``  ~\\Documents\\TypingTrainer\\                the user's outputs
* ``texts_dir()``      ~\\Documents\\TypingTrainer\\Texts\\         the user's own .txt corpora

Every accessor creates its folder on first use, so there is no install step. The
``TYPINGTRAINER_HOME`` environment variable redirects state and cache together (tests,
portable use); documents_dir/texts_dir are not affected by it, matching the plan's
"outside the repo" layout. Nothing here ever points inside the repository, which is
the git-tracked checkout, not a data store.
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

APP = "TypingTrainer"
ENV_HOME = "TYPINGTRAINER_HOME"

REPO: Path = Path(__file__).resolve().parents[2]


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _home() -> Path | None:
    env = os.environ.get(ENV_HOME)
    return Path(env) if env else None


def state_dir() -> Path:
    """Settings, history and per-text positions. Overridden by TYPINGTRAINER_HOME."""
    home = _home()
    return _ensure(home if home else Path(platformdirs.user_data_dir(APP, appauthor=False, roaming=False)))


def cache_dir() -> Path:
    """Reserved for downloaded/derived data; safe to delete. Overridden by TYPINGTRAINER_HOME."""
    home = _home()
    return _ensure(home / "Cache" if home else Path(platformdirs.user_cache_dir(APP, appauthor=False)))


def documents_dir() -> Path:
    """The user's outputs; not affected by TYPINGTRAINER_HOME."""
    return _ensure(Path(platformdirs.user_documents_dir()) / APP)


def texts_dir() -> Path:
    """The user's own .txt corpora, alongside the bundled sample text."""
    return _ensure(documents_dir() / "Texts")


def display(path: Path) -> str:
    """Label ``path`` by which root it is under, for logs and `where.py`.

    Never raises: a ``relative_to()`` on a path that isn't under any known root (or a
    ``TYPINGTRAINER_HOME`` override that has moved) breaks the moment layouts change,
    so this falls back to the plain string instead of letting that surface in a log line.
    """
    roots = {
        "state": state_dir(),
        "cache": cache_dir(),
        "documents": documents_dir(),
        "repo": REPO,
    }
    try:
        resolved = Path(path).resolve()
    except OSError:
        return str(path)
    for label, root in roots.items():
        try:
            return f"[{label}] {resolved.relative_to(root)}"
        except ValueError:
            continue
    return str(resolved)


def describe() -> dict[str, str]:
    """Every resolved location, for `pixi run where` and the README."""
    return {
        "repo": str(REPO),
        "state": str(state_dir()),
        "cache": str(cache_dir()),
        "documents": str(documents_dir()),
        "texts": str(texts_dir()),
        "home_override": os.environ.get(ENV_HOME, ""),
    }
