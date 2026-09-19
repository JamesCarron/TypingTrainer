"""Golden tests for typingtrainer.scoring: compare_lines, typing_score, passing_grade.

Covers compare_lines against a shared JSON fixture (tests/fixtures/diff_corpus.json,
also consumed by a later JS parity stage), typing_score against exact accuracy/WPM
values captured by running the current code (not hand-computed), and passing_grade
across its four require_accuracy/require_wpm criteria combinations plus the
accuracy > 1 ValueError.
"""

import json
from pathlib import Path

import pytest

from typingtrainer.scoring import compare_lines, passing_grade, typing_score

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_compare_lines_equal_strings():
    assert compare_lines("hello", "hello") == [True] * 5


def test_compare_lines_guess_shorter():
    assert compare_lines("he", "hello") == [True, True, False, False, False]


def test_compare_lines_guess_longer():
    assert compare_lines("hello!!", "hello") == [True, True, True, True, True, False, False]


def test_compare_lines_both_empty():
    assert compare_lines("", "") == []


def test_compare_lines_unicode():
    # accented characters compare per code point, like any other character
    assert compare_lines("café", "cafe") == [True, True, True, False]
    assert compare_lines("café", "café") == [True] * 4


def test_compare_lines_diff_corpus():
    """Every (target, typed) pair in the shared fixture must reproduce its recorded matches."""
    with open(FIXTURES_DIR / "diff_corpus.json", encoding="utf-8") as f:
        corpus = json.load(f)
    assert len(corpus) >= 20
    for case in corpus:
        assert compare_lines(case["typed"], case["target"]) == case["matches"], case


# typing_score: exact accuracy/WPM values produced by the current code (captured by
# running it, not hand-computed -- see scratch/gen_corpus-style probes used to derive
# these while writing this test).


def test_typing_score_perfect_match():
    result = typing_score("hello world", "hello world", 5.0)
    assert result == {
        "matches": [True] * 11,
        "accuracy": 1.0,
        "wpm": 26.4,
        "duration": 5.0,
    }


def test_typing_score_one_char_wrong():
    result = typing_score("hallo world", "hello world", 4.0)
    assert result["matches"] == [True, False, True, True, True, True, True, True, True, True, True]
    assert result["accuracy"] == 0.9091
    assert result["wpm"] == 30.0
    assert result["duration"] == 4.0


def test_typing_score_empty_guess():
    result = typing_score("", "abc", 2.0)
    assert result == {
        "matches": [False, False, False],
        "accuracy": 0.0,
        "wpm": 0.0,
        "duration": 2.0,
    }


def test_typing_score_totally_wrong_guess():
    result = typing_score("xyz", "abcdef", 1.0)
    assert result["accuracy"] == 0.0
    assert result["wpm"] == 0.0


def test_typing_score_empty_answer_raises_zero_division():
    """Known quirk of the current code, preserved verbatim: an empty answer divides by
    zero in the accuracy calculation. See the report accompanying this test suite --
    not fixed here, just pinned so a later refactor notices if it silently changes."""
    with pytest.raises(ZeroDivisionError):
        typing_score("abc", "", 1.0)


# passing_grade: copied from Game.passing_grade. Note the ValueError for accuracy > 1
# only fires when require_accuracy is set, since the check lives inside that branch in
# the original code -- preserved as-is.


def test_passing_grade_accuracy_only_pass():
    results = {"accuracy": 1.0, "wpm": 10.0}
    assert passing_grade(
        results, require_accuracy=True, min_accuracy=1.0, require_wpm=False, min_wpm=0
    )


def test_passing_grade_accuracy_only_fail():
    results = {"accuracy": 0.5, "wpm": 100.0}
    assert not passing_grade(
        results, require_accuracy=True, min_accuracy=1.0, require_wpm=False, min_wpm=0
    )


def test_passing_grade_wpm_only_pass():
    results = {"accuracy": 0.1, "wpm": 50.0}
    assert passing_grade(
        results, require_accuracy=False, min_accuracy=1.0, require_wpm=True, min_wpm=30.0
    )


def test_passing_grade_wpm_only_fail():
    results = {"accuracy": 0.1, "wpm": 10.0}
    assert not passing_grade(
        results, require_accuracy=False, min_accuracy=1.0, require_wpm=True, min_wpm=30.0
    )


def test_passing_grade_both_required_pass():
    results = {"accuracy": 1.0, "wpm": 50.0}
    assert passing_grade(
        results, require_accuracy=True, min_accuracy=1.0, require_wpm=True, min_wpm=30.0
    )


def test_passing_grade_both_required_fail_on_wpm():
    results = {"accuracy": 1.0, "wpm": 10.0}
    assert not passing_grade(
        results, require_accuracy=True, min_accuracy=1.0, require_wpm=True, min_wpm=30.0
    )


def test_passing_grade_neither_required_always_passes():
    results = {"accuracy": 0.0, "wpm": 0.0}
    assert passing_grade(
        results, require_accuracy=False, min_accuracy=1.0, require_wpm=False, min_wpm=0
    )


def test_passing_grade_accuracy_over_one_raises():
    results = {"accuracy": 1.5, "wpm": 10.0}
    with pytest.raises(ValueError):
        passing_grade(
            results, require_accuracy=True, min_accuracy=1.0, require_wpm=False, min_wpm=0
        )


def test_passing_grade_accuracy_over_one_does_not_raise_when_not_required():
    """Quirk preserved from the original: the >1 check lives inside the
    require_accuracy branch, so an impossible accuracy value silently passes
    through when require_accuracy is False."""
    results = {"accuracy": 1.5, "wpm": 10.0}
    assert passing_grade(
        results, require_accuracy=False, min_accuracy=1.0, require_wpm=False, min_wpm=0
    )
