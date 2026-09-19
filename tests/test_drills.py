"""tests/test_drills.py -- the improvement loop: turning a report into practice.

Report dicts are built by hand here, matching the real shapes ``analysis.py``
returns (character_error_rates.characters, confusion_pairs.pairs,
speed.bigram_latencies.bigrams, weak_points.problem_words.words,
progress.learning_curve.points) rather than invented ones, so every
ranking/score/generated-string assertion below was worked out against those
exact shapes.

``isolated`` is copied from tests/test_session.py's fixture of the same name:
every test that touches the real store or config runs against a temporary
state root and a temporary documents root, never the user's real
%LOCALAPPDATA%\\TypingTrainer or ~\\Documents\\TypingTrainer.
"""

from __future__ import annotations

import string

import platformdirs
import pytest

from typingtrainer import config, drills, history
from typingtrainer import session as session_mod


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A state root and a documents root that exist only for this test."""
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(tmp_path / "docs"))
    return tmp_path


# ---------------------------------------------------------------------------
# weak_targets
# ---------------------------------------------------------------------------


def test_weak_targets_empty_report_is_empty():
    report = {"weak_points": {}, "speed": {}, "progress": {}}
    assert drills.weak_targets(report) == []


def test_weak_targets_no_timing_data_still_ranks_char_and_confusion():
    """A report with weak points but no keystroke/bigram data at all."""
    report = {
        "weak_points": {
            "character_error_rates": {
                "characters": [
                    {"char": "e", "seen": 10, "mistyped": 5, "error_rate": 0.5},
                ]
            },
            "confusion_pairs": {"pairs": [{"intended": "e", "typed": "r", "count": 14}]},
        },
        "speed": {},
        "progress": {},
    }
    targets = drills.weak_targets(report)
    kinds = {t["kind"] for t in targets}
    assert kinds == {"char", "confusion"}
    assert all(t["kind"] != "bigram" for t in targets)


def test_weak_targets_ranking_scores_and_reasons():
    report = {
        "weak_points": {
            "character_error_rates": {
                "characters": [
                    {"char": "e", "seen": 10, "mistyped": 5, "error_rate": 0.5},
                    {"char": "a", "seen": 20, "mistyped": 2, "error_rate": 0.1},
                    # excluded: whitespace target
                    {"char": " ", "seen": 50, "mistyped": 40, "error_rate": 0.8},
                    # excluded: below the minimum sample floor
                    {"char": "x", "seen": 2, "mistyped": 2, "error_rate": 1.0},
                ]
            },
            "confusion_pairs": {
                "pairs": [
                    {"intended": "e", "typed": "r", "count": 14},
                    # excluded: below the minimum confusion-count floor
                    {"intended": "a", "typed": "s", "count": 1},
                ]
            },
        },
        "speed": {
            "bigram_latencies": {
                "bigrams": [
                    {"prev": "t", "char": "h", "count": 30, "mean_ms": 480.0, "median_ms": 460.0},
                    {"prev": "n", "char": "g", "count": 10, "mean_ms": 200.0, "median_ms": 190.0},
                ]
            }
        },
        "progress": {},
    }
    targets = drills.weak_targets(report)

    # median of [480, 200] = 340 -> th ratio 480/340 = 1.4117.. -> "1.4x"
    assert [(t["kind"], t["target"], t["score"]) for t in targets] == [
        ("char", "e", 1.0),
        ("confusion", "e>r", 1.0),
        ("bigram", "th", 1.0),
        ("char", "a", 0.5),
        ("bigram", "ng", 0.5),
    ]

    by_target = {(t["kind"], t["target"]): t for t in targets}
    assert by_target[("char", "e")]["reason"] == "mistyped 5 times in 10 attempts (50% error rate)"
    assert by_target[("confusion", "e>r")]["reason"] == "typed 'r' instead of 'e', 14 times"
    assert (
        by_target[("bigram", "th")]["reason"]
        == "averages 480 ms, 1.4x your median transition speed of 340 ms"
    )


def test_weak_targets_respects_limit():
    report = {
        "weak_points": {
            "character_error_rates": {
                "characters": [
                    {"char": c, "seen": 10, "mistyped": 5, "error_rate": 0.5} for c in "eart"
                ]
            }
        },
        "speed": {},
        "progress": {},
    }
    assert len(drills.weak_targets(report, limit=2)) == 2


# ---------------------------------------------------------------------------
# generate_drill
# ---------------------------------------------------------------------------


def test_generate_drill_empty_targets_is_empty_string():
    assert drills.generate_drill([]) == ""


def test_generate_drill_is_deterministic_with_a_seed():
    targets = [
        {"kind": "char", "target": "e", "score": 1.0, "reason": "x"},
        {"kind": "bigram", "target": "th", "score": 0.8, "reason": "y"},
    ]
    first = drills.generate_drill(targets, seed=42)
    second = drills.generate_drill(targets, seed=42)
    assert first == second
    assert first != ""


def test_generate_drill_differs_across_seeds():
    targets = [
        {"kind": "char", "target": "e", "score": 1.0, "reason": "x"},
        {"kind": "char", "target": "a", "score": 0.6, "reason": "y"},
        {"kind": "bigram", "target": "th", "score": 0.5, "reason": "z"},
    ]
    results = {drills.generate_drill(targets, length=80, seed=s) for s in range(8)}
    assert len(results) > 1


def test_generate_drill_only_contains_typeable_characters_and_the_target():
    targets = [{"kind": "char", "target": "q", "score": 1.0, "reason": "x"}]
    line = drills.generate_drill(targets, length=50, seed=7)
    assert line  # non-empty
    assert "q" in line
    assert set(line) <= set(string.ascii_lowercase + " ")
    assert len(line) <= 55  # a sensible length, allowing for whole-word rounding


def test_generate_drill_falls_back_to_synthesized_word_for_a_digit():
    """The word bank has no digits in it, so a digit target must fall back."""
    targets = [{"kind": "char", "target": "5", "score": 1.0, "reason": "x"}]
    line = drills.generate_drill(targets, length=20, seed=3)
    assert "5" in line
    assert set(line) <= set(string.ascii_lowercase + string.digits + " ")


def test_generate_drill_word_boundary_bigram_does_not_create_double_spaces():
    """A bigram target that straddles a word boundary (e.g. " a") has no
    word-bank match and no sensible pseudo-word -- it must fall back to a
    plain word, not to embedding the space inside a pool entry, which would
    silently produce a double space once entries are joined."""
    targets = [{"kind": "bigram", "target": " a", "score": 1.0, "reason": "x"}]
    for seed in range(10):
        line = drills.generate_drill(targets, length=40, seed=seed)
        assert "  " not in line
        assert set(line) <= set(string.ascii_lowercase + " ")


def test_generate_drill_confusion_and_bigram_targets_produce_relevant_words():
    targets = [
        {"kind": "confusion", "target": "e>r", "score": 1.0, "reason": "x"},
        {"kind": "bigram", "target": "th", "score": 0.9, "reason": "y"},
    ]
    line = drills.generate_drill(targets, length=60, seed=1)
    assert "e" in line
    assert "th" in line


# ---------------------------------------------------------------------------
# find_hard_line
# ---------------------------------------------------------------------------


def test_find_hard_line_ranks_by_weighted_density():
    lines = [
        "the cat sat on the mat",
        "a quick brown fox jumps",
        "threading threads together",
    ]
    targets = [
        {"kind": "char", "target": "t", "score": 1.0},
        {"kind": "bigram", "target": "th", "score": 0.8},
    ]
    results = drills.find_hard_line(lines, targets, start=0, limit=5)

    # line 1 has neither 't' nor 'th' and must be dropped entirely
    assert [r["line_index"] for r in results] == [0, 2]
    assert results[0]["score"] == pytest.approx(0.3, abs=1e-6)
    assert results[1]["score"] == pytest.approx(round(6.4 / 26, 4), abs=1e-6)
    assert {"kind": "char", "target": "t", "count": 5} in results[0]["targets_matched"]
    assert {"kind": "bigram", "target": "th", "count": 2} in results[0]["targets_matched"]


def test_find_hard_line_respects_start_and_limit():
    lines = [
        "the cat sat on the mat",
        "a quick brown fox jumps",
        "threading threads together",
    ]
    targets = [{"kind": "char", "target": "t", "score": 1.0}]

    results = drills.find_hard_line(lines, targets, start=1, limit=5)
    assert [r["line_index"] for r in results] == [2]

    results = drills.find_hard_line(lines, targets, start=0, limit=1)
    assert len(results) == 1


def test_find_hard_line_no_matches_is_empty():
    lines = ["zzz zzz zzz"]
    targets = [{"kind": "char", "target": "q", "score": 1.0}]
    assert drills.find_hard_line(lines, targets) == []


# ---------------------------------------------------------------------------
# trouble_words
# ---------------------------------------------------------------------------


def test_trouble_words_reshapes_and_truncates():
    report = {
        "weak_points": {
            "problem_words": {
                "words": [
                    {"word": "necessary", "count": 8, "example_typed": "neccessary"},
                    {"word": "the", "count": 2, "example_typed": "teh"},
                ]
            }
        }
    }
    assert drills.trouble_words(report, limit=1) == [
        {"word": "necessary", "count": 8, "common_wrong_version": "neccessary"}
    ]
    assert len(drills.trouble_words(report, limit=50)) == 2


def test_trouble_words_empty_report_is_empty():
    assert drills.trouble_words({"weak_points": {}}) == []


# ---------------------------------------------------------------------------
# suggest_criteria
# ---------------------------------------------------------------------------


def test_suggest_criteria_no_data_proposes_no_change():
    report = {"progress": {"learning_curve": {"points": []}}}
    settings = config.Settings(min_wpm=50.0, min_accuracy=0.95)
    result = drills.suggest_criteria(report, settings)
    assert result["proposed_min_wpm"] == 50.0
    assert result["proposed_min_accuracy"] == 0.95
    assert "not enough" in result["reasoning"]


def test_suggest_criteria_raises_the_bar_after_improvement():
    report = {
        "progress": {
            "learning_curve": {
                "points": [
                    {
                        "key": "1",
                        "wpm": 80.0,
                        "accuracy": 0.99,
                        "rolling_mean_wpm": 66.0,
                        "rolling_mean_accuracy": 0.995,
                    }
                ]
            }
        }
    }
    settings = config.Settings(min_wpm=50.0, min_accuracy=0.95)
    result = drills.suggest_criteria(report, settings)
    assert result["current_min_wpm"] == 50.0
    assert result["proposed_min_wpm"] == 58.0  # 50 + (66-50)*0.5
    assert result["proposed_min_accuracy"] == 0.97  # 0.95 + 0.02 cap
    assert result["proposed_min_wpm"] >= result["current_min_wpm"]
    assert result["proposed_min_accuracy"] >= result["current_min_accuracy"]
    assert "modest step up" in result["reasoning"]


def test_suggest_criteria_never_lowers_the_bar_when_performance_dips():
    report = {
        "progress": {
            "learning_curve": {
                "points": [
                    {
                        "key": "1",
                        "wpm": 40.0,
                        "accuracy": 0.90,
                        "rolling_mean_wpm": 42.0,  # below current min_wpm
                        "rolling_mean_accuracy": 0.90,  # below current min_accuracy
                    }
                ]
            }
        }
    }
    settings = config.Settings(min_wpm=50.0, min_accuracy=0.95)
    result = drills.suggest_criteria(report, settings)
    assert result["proposed_min_wpm"] == 50.0
    assert result["proposed_min_accuracy"] == 0.95
    assert "no change" in result["reasoning"]


def test_suggest_criteria_marginal_improvement_does_not_trigger_a_raise():
    """Just barely above the current bar is noise, not room to raise it."""
    report = {
        "progress": {
            "learning_curve": {
                "points": [
                    {
                        "key": "1",
                        "wpm": 52.0,
                        "accuracy": 0.955,
                        "rolling_mean_wpm": 52.0,
                        "rolling_mean_accuracy": 0.955,
                    }
                ]
            }
        }
    }
    settings = config.Settings(min_wpm=50.0, min_accuracy=0.95)
    result = drills.suggest_criteria(report, settings)
    assert result["proposed_min_wpm"] == 50.0
    assert result["proposed_min_accuracy"] == 0.95


def test_suggest_criteria_accepts_a_plain_dict_of_settings():
    report = {"progress": {"learning_curve": {"points": []}}}
    result = drills.suggest_criteria(report, {"min_wpm": 30.0, "min_accuracy": 1.0})
    assert result["current_min_wpm"] == 30.0
    assert result["current_min_accuracy"] == 1.0


# ---------------------------------------------------------------------------
# practice_plan (the store-touching entry point)
# ---------------------------------------------------------------------------


def test_practice_plan_empty_history_is_valid_not_an_exception(isolated):
    plan = drills.practice_plan()
    assert plan["has_enough_data"] is False
    assert plan["message"] == "not enough data yet, keep typing"
    assert plan["targets"] == []
    assert plan["drill"] == ""
    assert plan["hard_lines"] == []
    assert plan["trouble_words"] == []
    assert plan["criteria_suggestion"]["proposed_min_wpm"] == plan["criteria_suggestion"][
        "current_min_wpm"
    ]


def test_practice_plan_empty_history_for_named_text_is_also_valid(isolated):
    plan = drills.practice_plan(text_name="nonexistent text")
    assert plan["has_enough_data"] is False
    assert plan["text_name"] == "nonexistent text"


def test_practice_plan_with_data_produces_targets_and_a_typeable_drill(isolated, monkeypatch):
    bundled = isolated / "bundled"
    bundled.mkdir()
    (bundled / "tiny.txt").write_text(
        "there are three trees over there\n"
        "the weather report repeats every hour\n"
        "a quick brown fox jumps over the lazy dog\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(session_mod, "BUNDLED_DIR", bundled)
    monkeypatch.setattr(session_mod, "BUNDLED_NAMES", {})

    # Twelve synthetic attempts on "tiny", consistently typing 'r' where the
    # target has 'e', so character_error_rates/confusion_pairs both light up.
    target_line = "there are three trees over there"
    typed_line = target_line.replace("e", "r")
    for i in range(12):
        history.append_attempt(
            {
                "EventTime": f"0{(i % 9) + 1}-01-2026 12:00:0{i % 9}",
                "TextName": "tiny",
                "Length": len(target_line),
                "Duration": 6.0,
                "Accuracy": 0.7,
                "Wpm": 45.0,
                "Answer": target_line,
                "user_input": typed_line,
                "user_input_full": typed_line,
                "Passed": False,
                "LineIndex": 0,
            },
            key=f"attempt-{i}",
            keystrokes=[
                {"char": c, "ms": float(j * 90), "correct": c == target_line[j] if j < len(target_line) else None}
                for j, c in enumerate(typed_line)
            ],
        )
    history.set_position("tiny", 0)

    plan = drills.practice_plan(text_name="tiny")

    assert plan["has_enough_data"] is True
    assert plan["message"] is None
    assert plan["targets"], "expected at least one weak target from consistent e->r errors"
    assert all(0.0 < t["score"] <= 1.0 for t in plan["targets"])
    assert plan["drill"] != ""
    assert set(plan["drill"]) <= set(string.ascii_lowercase + string.digits + " ")
    assert isinstance(plan["hard_lines"], list)
    assert isinstance(plan["trouble_words"], list)
    assert "proposed_min_wpm" in plan["criteria_suggestion"]
