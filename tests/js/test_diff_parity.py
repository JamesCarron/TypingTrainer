"""Parity test: the browser's live diff must equal scoring.compare_lines.

Runs the real src/typingtrainer/static/page.js diff() function under node
(via tests/js/diff_runner.mjs) over every pair in the one shared fixture,
tests/fixtures/diff_corpus.json, and asserts the result equals both the
fixture's committed "matches" and a fresh call to Python's own
scoring.compare_lines. One fixture, two implementations -- a second fixture
list would be the same bug as a second implementation (docs/Contracts.md).

Skips (does not fail) if `node` is not on PATH.

Written 2026-09-19 for stage 6 of the TypingTrainer refactor
(docs/Refactor_Plan.md).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from typingtrainer.scoring import compare_lines

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "diff_corpus.json"
PAGE_JS = REPO_ROOT / "src" / "typingtrainer" / "static" / "page.js"
RUNNER = Path(__file__).resolve().parent / "diff_runner.mjs"


def _run_js_diff(pairs):
    proc = subprocess.run(
        ["node", str(RUNNER), str(PAGE_JS)],
        input=json.dumps(pairs).encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return json.loads(proc.stdout.decode("utf-8"))


def test_js_diff_matches_fixture_and_python():
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")

    corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert corpus, "diff_corpus.json fixture is empty"

    pairs = [{"target": row["target"], "typed": row["typed"]} for row in corpus]
    js_results = _run_js_diff(pairs)

    assert len(js_results) == len(corpus)
    for fixture_row, js_row in zip(corpus, js_results):
        target = fixture_row["target"]
        typed = fixture_row["typed"]
        expected = fixture_row["matches"]
        python_matches = compare_lines(typed, target)

        assert js_row["matches"] == expected, (
            f"JS diff({typed!r}, {target!r}) = {js_row['matches']!r}, "
            f"fixture expected {expected!r}"
        )
        assert js_row["matches"] == python_matches, (
            f"JS diff({typed!r}, {target!r}) = {js_row['matches']!r}, "
            f"scoring.compare_lines gave {python_matches!r}"
        )
