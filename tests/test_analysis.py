"""tests/test_analysis.py -- the analysis engine: hand-verified statistics.

Every non-trivial number here is computed by hand in the test itself (in a
comment or inline), not just asserted against whatever the code happens to
produce. Covers the empty-history case, the no-keystrokes case and the
messy-legacy-record case (no Length, no Passed, an unformatted EventTime) for
every function family, per the brief in docs/UI_Refresh_Notes.md.

TYPINGTRAINER_HOME and platformdirs.user_documents_dir are isolated in every
test that touches the store (only the full_report tests do); the pure
functions take plain lists and need no isolation at all.
"""

from __future__ import annotations

from datetime import date

import platformdirs
import pytest

from typingtrainer import analysis, history


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def rec(**kwargs) -> dict:
    return dict(kwargs)


def A(key: str, **kwargs) -> tuple:
    """One (key, record) pair, as history.iter_attempts yields."""
    return (key, rec(**kwargs))


def K(char, ms, correct=True) -> dict:
    return {"char": char, "ms": ms, "correct": correct}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPINGTRAINER_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(tmp_path / "docs"))
    return tmp_path


# ---------------------------------------------------------------------------
# empty history -- every family, must never raise or divide by zero
# ---------------------------------------------------------------------------


def test_empty_history_weak_points():
    assert analysis.confusion_pairs([]) == {
        "pairs": [],
        "attempts_considered": 0,
        "skipped_missing_fields": 0,
        "skipped_length_mismatch": 0,
    }
    assert analysis.character_error_rates([])["characters"] == []
    assert analysis.problem_words([])["words"] == []
    assert analysis.error_categories([])["categories"] == []
    cr = analysis.correction_rate([])
    assert cr["overall_correction_rate"] == 0.0
    assert cr["per_attempt"] == []


def test_empty_history_speed():
    assert analysis.key_latencies([]) == {"keys": [], "instrumented_attempts": 0}
    bl = analysis.bigram_latencies([])
    assert bl["bigrams"] == []
    sf = analysis.same_finger_bigrams([])
    assert sf["pairs"] == []
    assert sf["same_finger_mean_ms"] is None
    assert sf["all_bigrams_mean_ms"] is None
    r = analysis.rhythm([])
    assert r["mean_ms"] is None
    assert r["stdev_ms"] == 0.0
    assert r["stall_count"] == 0
    et = analysis.error_timing([])
    assert et["interpretation"] == "insufficient data"
    assert et["n_errors_with_timing"] == 0


def test_empty_history_progress():
    lc = analysis.learning_curve([])
    assert lc["points"] == []
    apl = analysis.attempts_per_line([])
    assert apl["lines"] == []
    da = analysis.daily_activity([])
    assert da["days"] == []
    ss = analysis.session_summary([])
    assert ss["lines_completed"] == 0
    assert ss["mean_wpm"] is None
    assert ss["best_line"] is None
    os_ = analysis.overall_stats([], today=date(2026, 9, 19))
    assert os_["total_attempts"] == 0
    assert os_["top_wpm"] is None
    assert os_["current_streak_days"] == 0
    assert os_["longest_streak_days"] == 0


def test_full_report_on_empty_store(isolated):
    report = analysis.full_report()
    assert report["data_coverage"] == {
        "text_name": None,
        "total_attempts": 0,
        "instrumented_attempts": 0,
    }
    assert set(report) == {"data_coverage", "weak_points", "speed", "progress"}


# ---------------------------------------------------------------------------
# weak points
# ---------------------------------------------------------------------------


def test_confusion_pairs_basic_and_skips():
    attempts = [
        A("k1", Answer="cat", user_input="cat"),  # no errors
        A("k2", Answer="cat", user_input="cot"),  # a -> o
        A("k3", Answer="cat", user_input="bat"),  # c -> b
        A("k4", Answer="cat", user_input="ca"),  # short by 1: usable, trailing pos skipped
        A("k5", Answer="catnap", user_input="cat"),  # short by 3: skipped_length
        A("k6", TextName="x"),  # no Answer at all: skipped_missing
    ]
    result = analysis.confusion_pairs(attempts)
    assert result["pairs"] == [
        {"intended": "a", "typed": "o", "count": 1},
        {"intended": "c", "typed": "b", "count": 1},
    ]
    assert result["attempts_considered"] == 4  # k1, k2, k3, k4
    assert result["skipped_length_mismatch"] == 1  # k5
    assert result["skipped_missing_fields"] == 1  # k6


def test_character_error_rates_hand_computed():
    attempts = [
        A("k1", Answer="ab", user_input="ab"),  # both correct
        A("k2", Answer="ab", user_input="aa"),  # b -> a wrong
        A("k3", Answer="ab", user_input="xb"),  # a -> x wrong
    ]
    result = analysis.character_error_rates(attempts)
    by_char = {row["char"]: row for row in result["characters"]}
    assert by_char["a"]["seen"] == 3
    assert by_char["a"]["mistyped"] == 1
    assert by_char["a"]["error_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert by_char["b"]["seen"] == 3
    assert by_char["b"]["mistyped"] == 1
    assert result["attempts_considered"] == 3


def test_problem_words_counts_and_examples():
    attempts = [
        A("k1", Answer="the cat sat", user_input="the cat sat"),
        A("k2", Answer="the cat sat", user_input="the bat sat"),  # cat -> bat
        A("k3", Answer="the cat sat", user_input="the cat mat"),  # sat -> mat
    ]
    result = analysis.problem_words(attempts)
    words = {row["word"]: row for row in result["words"]}
    assert words["cat"]["count"] == 1
    assert words["cat"]["example_typed"] == "bat"
    assert words["sat"]["count"] == 1
    assert words["sat"]["example_typed"] == "mat"
    assert "the" not in words


def test_error_categories_one_error_per_class():
    answer = "Ab1 !'"  # upper, lower, digit, space, punct, quote
    attempts = [
        A("k0", Answer=answer, user_input=answer),  # baseline, all correct
        A("k1", Answer=answer, user_input="ab1 !'"),  # upper wrong (A->a)
        A("k2", Answer=answer, user_input="Ac1 !'"),  # lower wrong (b->c)
        A("k3", Answer=answer, user_input="Ab2 !'"),  # digit wrong (1->2)
        A("k4", Answer=answer, user_input="Ab1_!'"),  # space wrong (' '->'_')
        A("k5", Answer=answer, user_input="Ab1 ?'"),  # punct wrong (!->?)
        A("k6", Answer=answer, user_input="Ab1 !\""),  # quote wrong ('->")
    ]
    result = analysis.error_categories(attempts)
    by_cat = {row["category"]: row for row in result["categories"]}
    for cat in ("upper", "lower", "digit", "space", "punct", "quote"):
        assert by_cat[cat]["seen"] == 7, cat
        assert by_cat[cat]["mistyped"] == 1, cat
        assert by_cat[cat]["error_rate"] == pytest.approx(1 / 7, abs=1e-3)


def test_correction_rate_hand_computed():
    attempts = [
        A("k1", user_input="cat", user_input_full="cat"),  # no correction
        A("k2", user_input="cat", user_input_full="caat"),  # 1 extra of 4
        A("k3", user_input="cat"),  # no user_input_full: skipped
    ]
    result = analysis.correction_rate(attempts)
    assert result["skipped_missing_fields"] == 1
    assert result["attempts_considered"] == 2
    assert result["total_extra_chars"] == 1
    # overall = 1 extra / (3 + 4) total full chars = 1/7
    assert result["overall_correction_rate"] == pytest.approx(1 / 7, abs=1e-3)
    per = {r["key"]: r for r in result["per_attempt"]}
    assert per["k1"]["extra_chars"] == 0
    assert per["k2"]["extra_chars"] == 1
    assert per["k2"]["correction_rate"] == pytest.approx(0.25)


def test_weak_points_on_messy_legacy_record():
    """No Length, no Passed, an unformatted EventTime -- must not raise."""
    legacy = A(
        "k1",
        EventTime="{self.time_start:%d-%m-%Y %H:%M:%S}",
        TextName="Legacy",
        Answer="cat",
        user_input="cat",
        user_input_full="cat",
        Duration=3.0,
        Wpm=40,
        Accuracy=1.0,
        # no Length, no Passed
    )
    assert analysis.confusion_pairs([legacy])["attempts_considered"] == 1
    assert analysis.character_error_rates([legacy])["attempts_considered"] == 1
    assert analysis.error_categories([legacy])["attempts_considered"] == 1
    assert analysis.correction_rate([legacy])["attempts_considered"] == 1


# ---------------------------------------------------------------------------
# speed
# ---------------------------------------------------------------------------


def test_key_latencies_hand_computed():
    instrumented = [
        ("k1", {}, [K("a", 0), K("b", 100), K("c", 250, correct=False)]),
    ]
    result = analysis.key_latencies(instrumented)
    by_char = {row["char"]: row for row in result["keys"]}
    assert "a" not in by_char  # first key of the line has no prior gap
    assert by_char["b"]["count"] == 1
    assert by_char["b"]["mean_ms"] == pytest.approx(100.0)
    assert by_char["c"]["mean_ms"] == pytest.approx(150.0)
    assert result["instrumented_attempts"] == 1


def test_bigram_latencies_threshold_and_mean():
    instrumented = [
        ("k1", {}, [K("a", 0), K("b", 100)]),  # a->b = 100ms
        ("k2", {}, [K("a", 0), K("b", 120)]),  # a->b = 120ms
    ]
    below_threshold = analysis.bigram_latencies(instrumented, min_occurrences=3)
    assert below_threshold["bigrams"] == []  # only 2 occurrences, threshold is 3

    at_threshold = analysis.bigram_latencies(instrumented, min_occurrences=2)
    assert len(at_threshold["bigrams"]) == 1
    row = at_threshold["bigrams"][0]
    assert row == {"prev": "a", "char": "b", "count": 2, "mean_ms": pytest.approx(110.0), "median_ms": pytest.approx(110.0)}


def test_same_finger_bigrams_excludes_repeats_and_different_fingers():
    # r and f are both L-index in QWERTY_FINGER_MAP: a genuine same-finger reach.
    instrumented = [
        ("k1", {}, [K("r", 0), K("f", 80)]),  # r->f, same finger, 80ms
        ("k2", {}, [K("r", 0), K("f", 100)]),  # r->f, same finger, 100ms
        ("k3", {}, [K("r", 0), K("r", 60)]),  # repeat key: excluded on purpose
        ("k4", {}, [K("a", 0), K("b", 50)]),  # a=L-pinky, b=L-index: different fingers
    ]
    result = analysis.same_finger_bigrams(instrumented, min_occurrences=2)
    assert len(result["pairs"]) == 1
    row = result["pairs"][0]
    assert row["prev"] == "r" and row["char"] == "f"
    assert row["count"] == 2
    assert row["mean_ms"] == pytest.approx(90.0)
    assert row["finger"] == "L-index"


def test_rhythm_hand_computed_stall_and_stats():
    instrumented = [("k1", {}, [K("a", 0), K("b", 100), K("c", 700), K("d", 750)])]
    # deltas: a->b=100, b->c=600, c->d=50; mean=250, stall (>500) at b->c only
    result = analysis.rhythm(instrumented, stall_ms=500.0)
    assert result["mean_ms"] == pytest.approx(250.0)
    assert result["stall_count"] == 1
    assert result["stalls"][0]["char"] == "c"
    assert result["stalls"][0]["gap_ms"] == pytest.approx(600.0)
    assert result["per_attempt"][0]["n_keys"] == 3


def test_error_timing_distinguishes_slow_from_fast():
    instrumented = [
        (
            "k1",
            {},
            [
                K("a", 0, correct=True),
                K("b", 100, correct=True),  # gap 100 before a correct key
                K("c", 250, correct=False),  # gap 150 before an error
                K("d", 300, correct=True),  # gap 50 before a correct key
            ],
        )
    ]
    result = analysis.error_timing(instrumented)
    assert result["mean_gap_before_correct_ms"] == pytest.approx(75.0)  # (100+50)/2
    assert result["mean_gap_before_error_ms"] == pytest.approx(150.0)
    assert "unfamiliarity" in result["interpretation"]


def test_speed_family_no_keystrokes_case():
    """An attempt with a record but zero recorded keystrokes: must not crash."""
    instrumented = []  # iter_keystroke_attempts never yields un-instrumented rows
    for fn in (analysis.key_latencies, analysis.bigram_latencies, analysis.same_finger_bigrams, analysis.rhythm, analysis.error_timing):
        result = fn(instrumented)
        assert result["instrumented_attempts"] == 0


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------


def test_learning_curve_rolling_mean_and_skip():
    attempts = [
        A("k1", Wpm=50, Accuracy=0.9),
        A("k2", Wpm=60, Accuracy=0.95),
        A("k3", Answer="x"),  # missing Wpm/Accuracy: skipped
        A("k4", Wpm=70, Accuracy=1.0),
    ]
    result = analysis.learning_curve(attempts, window=2)
    assert result["skipped_missing_fields"] == 1
    points = result["points"]
    assert len(points) == 3
    assert points[0]["rolling_mean_wpm"] == pytest.approx(50.0)
    assert points[1]["rolling_mean_wpm"] == pytest.approx(55.0)  # (50+60)/2
    assert points[2]["rolling_mean_wpm"] == pytest.approx(65.0)  # (60+70)/2, window=2
    assert points[2]["rolling_mean_accuracy"] == pytest.approx(0.975)  # (0.95+1.0)/2


def test_attempts_per_line_identifies_walls():
    attempts = [
        A("k1", Answer="line1", Passed=False),
        A("k2", Answer="line1", Passed=False),
        A("k3", Answer="line1", Passed=True),
        A("k4", Answer="line2", Passed=True),
        A("k5", TextName="no-answer"),  # skipped
    ]
    result = analysis.attempts_per_line(attempts)
    assert result["skipped_missing_fields"] == 1
    by_line = {r["line"]: r for r in result["lines"]}
    assert by_line["line1"] == {"line": "line1", "attempts": 3, "passed": 1}
    assert by_line["line2"] == {"line": "line2", "attempts": 1, "passed": 1}
    assert result["lines"][0]["line"] == "line1"  # sorted by attempts desc


def test_daily_activity_groups_by_day_and_skips_unparsable():
    attempts = [
        A("k1", EventTime="19-09-2026 10:00:00", Duration=4.0, Wpm=50),
        A("k2", EventTime="19-09-2026 11:00:00", Duration=6.0, Wpm=70),
        A("k3", EventTime="20-09-2026 09:00:00", Duration=5.0, Wpm=40),
        A("k4", EventTime="garbage-not-a-date"),
    ]
    result = analysis.daily_activity(attempts)
    assert result["skipped_unparsable_event_time"] == 1
    by_day = {d["date"]: d for d in result["days"]}
    assert by_day["2026-09-19"]["attempts"] == 2
    assert by_day["2026-09-19"]["duration_s"] == pytest.approx(10.0)
    assert by_day["2026-09-19"]["mean_wpm"] == pytest.approx(60.0)
    assert by_day["2026-09-20"]["attempts"] == 1


def test_session_summary_best_and_worst_line():
    attempts = [
        A("k1", Answer="l1", Passed=True, Duration=2.0, Wpm=50.0, Accuracy=1.0),
        A("k2", Answer="l2", Passed=False, Duration=3.0, Wpm=30.0, Accuracy=0.8),
        A("k3", Answer="l3", Passed=True, Duration=1.0, Wpm=90.0, Accuracy=0.95),
    ]
    result = analysis.session_summary(attempts)
    assert result["lines_completed"] == 3
    assert result["passed"] == 2
    assert result["failed"] == 1
    assert result["duration_s"] == pytest.approx(6.0)
    assert result["mean_wpm"] == pytest.approx((50 + 30 + 90) / 3, abs=1e-2)
    assert result["best_wpm"] == pytest.approx(90.0)
    assert result["best_line"]["line"] == "l3"
    assert result["worst_line"]["line"] == "l2"
    assert result["mean_accuracy"] == pytest.approx((1.0 + 0.8 + 0.95) / 3, abs=1e-4)


def test_session_summary_with_unknown_passed_field():
    """A legacy record with no Passed key: counted as a line, not pass or fail."""
    attempts = [A("k1", Answer="l1", Duration=2.0, Wpm=50.0, Accuracy=1.0)]
    result = analysis.session_summary(attempts)
    assert result["lines_completed"] == 1
    assert result["passed"] == 0
    assert result["failed"] == 0


def test_overall_stats_streaks():
    def day(d, wpm):
        return A(d, EventTime=f"{d} 09:00:00", Duration=1.0, Wpm=wpm, Accuracy=1.0)

    attempts = [
        day("10-09-2026", 40),
        day("17-09-2026", 50),
        day("18-09-2026", 55),
        day("19-09-2026", 60),
    ]
    result = analysis.overall_stats(attempts, today=date(2026, 9, 19))
    assert result["total_attempts"] == 4
    assert result["top_wpm"] == pytest.approx(60.0)
    assert result["mean_wpm"] == pytest.approx((40 + 50 + 55 + 60) / 4)
    assert result["longest_streak_days"] == 3  # 17, 18, 19
    assert result["current_streak_days"] == 3  # ends today
    assert result["active_days"] == 4


def test_overall_stats_streak_broken_by_idle_day():
    attempts = [
        A("k1", EventTime="10-09-2026 09:00:00", Duration=1.0, Wpm=40, Accuracy=1.0),
    ]
    # today is 3 days after the only active day: current streak is over.
    result = analysis.overall_stats(attempts, today=date(2026, 9, 13))
    assert result["current_streak_days"] == 0
    assert result["longest_streak_days"] == 1


def test_progress_family_on_messy_legacy_record():
    legacy = A(
        "k1",
        EventTime="{self.time_start:%d-%m-%Y %H:%M:%S}",
        TextName="Legacy",
        Answer="cat",
        user_input="cat",
        Duration=3.0,
        Wpm=40,
        Accuracy=1.0,
        # no Length, no Passed
    )
    assert analysis.learning_curve([legacy])["points"][0]["wpm"] == 40
    assert analysis.attempts_per_line([legacy])["lines"][0]["passed"] == 0
    da = analysis.daily_activity([legacy])
    assert da["skipped_unparsable_event_time"] == 1
    assert da["days"] == []
    ss = analysis.session_summary([legacy])
    assert ss["lines_completed"] == 1
    os_ = analysis.overall_stats([legacy], today=date(2026, 9, 19))
    assert os_["total_attempts"] == 1
    assert os_["top_wpm"] == pytest.approx(40.0)
    assert os_["active_days"] == 0  # EventTime unparsable, so no day to count


# ---------------------------------------------------------------------------
# full_report -- smoke test against a real (temporary) store
# ---------------------------------------------------------------------------


def test_full_report_shape_against_populated_store(isolated):
    for i in range(3):
        history.append_attempt(
            {
                "EventTime": f"1{i}-09-2026 10:00:00",
                "TextName": "Sample",
                "Length": 3,
                "Duration": 2.0,
                "Accuracy": 1.0,
                "Wpm": 50.0 + i,
                "Answer": "cat",
                "user_input": "cat",
                "user_input_full": "cat",
                "Passed": True,
                "LineIndex": i,
            },
            key=f"attempt-{i}",
        )
    history.append_attempt(
        {
            "EventTime": "19-09-2026 12:00:00",
            "TextName": "Sample",
            "Length": 3,
            "Duration": 1.5,
            "Accuracy": 0.67,
            "Wpm": 45.0,
            "Answer": "cat",
            "user_input": "cot",
            "user_input_full": "cot",
            "Passed": False,
            "LineIndex": 3,
        },
        key="attempt-3",
        keystrokes=[K("c", 0), K("o", 120, correct=False), K("t", 220)],
    )

    report = analysis.full_report()
    assert report["data_coverage"] == {
        "text_name": None,
        "total_attempts": 4,
        "instrumented_attempts": 1,
    }
    assert report["weak_points"]["confusion_pairs"]["pairs"] == [
        {"intended": "a", "typed": "o", "count": 1}
    ]
    assert report["speed"]["key_latencies"]["instrumented_attempts"] == 1
    assert report["progress"]["overall_stats"]["total_attempts"] == 4

    # filtering by text_name narrows the store reads
    filtered = analysis.full_report(text_name="Sample")
    assert filtered["data_coverage"]["total_attempts"] == 4
    empty = analysis.full_report(text_name="Nonexistent")
    assert empty["data_coverage"]["total_attempts"] == 0


# --- implausible-record guard (added 2026-09-19 after the real history turned
# --- up one corrupt row that set a fake personal best) -----------------------


def _attempt(key, **fields):
    record = {"TextName": "T", "Answer": "abc", "user_input": "abc"}
    record.update(fields)
    return (key, record)


def test_overall_stats_excludes_an_impossible_wpm():
    """The real store holds one 1236 wpm row with an empty input; it must not
    become the personal best, and it must be counted as excluded."""
    attempts = [
        _attempt("2026-09-01T10:00:00", Wpm=70.0, Accuracy=1.0, Duration=5.0,
                 EventTime="01-09-2026 10:00:00"),
        _attempt("2026-09-01T10:01:00", Wpm=1236.0, Accuracy=0.0, Duration=1.0,
                 user_input="", EventTime="01-09-2026 10:01:00"),
    ]
    stats = analysis.overall_stats(attempts, today=date(2026, 9, 1))
    assert stats["top_wpm"] == 70.0
    assert stats["mean_wpm"] == 70.0
    assert stats["excluded_implausible"] == 1
    # the attempt still happened, so it is still counted as one
    assert stats["total_attempts"] == 2


def test_overall_stats_excludes_a_zero_duration_attempt():
    attempts = [
        _attempt("k1", Wpm=60.0, Accuracy=1.0, Duration=4.0, EventTime="01-09-2026 10:00:00"),
        _attempt("k2", Wpm=90.0, Accuracy=1.0, Duration=0.0, EventTime="01-09-2026 10:01:00"),
    ]
    stats = analysis.overall_stats(attempts, today=date(2026, 9, 1))
    assert stats["top_wpm"] == 60.0
    assert stats["excluded_implausible"] == 1


def test_learning_curve_drops_implausible_points():
    attempts = [
        _attempt("k1", Wpm=70.0, Accuracy=1.0, Duration=5.0),
        _attempt("k2", Wpm=1236.0, Accuracy=0.0, Duration=1.0),
        _attempt("k3", Wpm=72.0, Accuracy=1.0, Duration=5.0),
    ]
    curve = analysis.learning_curve(attempts)
    assert [p["wpm"] for p in curve["points"]] == [70.0, 72.0]
    assert curve["skipped_implausible"] == 1
    assert curve["skipped_missing_fields"] == 0


def test_a_fast_but_plausible_attempt_is_kept():
    """The guard must not quietly delete a genuinely good run."""
    attempts = [_attempt("k1", Wpm=150.0, Accuracy=1.0, Duration=3.0,
                         EventTime="01-09-2026 10:00:00")]
    stats = analysis.overall_stats(attempts, today=date(2026, 9, 1))
    assert stats["top_wpm"] == 150.0
    assert stats["excluded_implausible"] == 0


# --- keystroke-derived confusions (added 2026-09-19: the submitted text is
# --- almost always perfect under a strict accuracy floor, so the real
# --- mistakes only exist in the keystrokes) ----------------------------------


def _instrumented(key, strokes):
    """(key, record, keystrokes) as history.iter_keystroke_attempts yields it."""
    return (key, {"TextName": "T", "Answer": "the", "user_input": "the"}, strokes)


def _k(char, expected, ms=100.0):
    return {"char": char, "expected": expected, "ms": ms, "correct": char == expected}


def test_keystroke_confusions_sees_a_corrected_mistake():
    """The submitted line is perfect; the mistake exists only in the keystrokes."""
    strokes = [_k("t", "t"), _k("r", "h"), _k("h", "h"), _k("e", "e")]
    got = analysis.keystroke_confusions([_instrumented("k1", strokes)])
    assert got["pairs"] == [{"intended": "h", "typed": "r", "count": 1}]
    assert got["total_errors"] == 1
    assert got["keystrokes_considered"] == 4
    assert got["attempts_with_expected"] == 1
    assert got["skipped_no_expected"] == 0


def test_keystroke_confusions_ranks_by_count():
    strokes = (
        [_k("r", "e") for _ in range(3)]
        + [_k("m", "n")]
        + [_k("a", "a") for _ in range(5)]
    )
    got = analysis.keystroke_confusions([_instrumented("k1", strokes)])
    assert got["pairs"][0] == {"intended": "e", "typed": "r", "count": 3}
    assert got["pairs"][1] == {"intended": "n", "typed": "m", "count": 1}


def test_keystroke_confusions_skips_strokes_recorded_before_the_field_existed():
    """Old keystrokes have no `expected`; it cannot be reconstructed, so they are
    counted as skipped rather than guessed at."""
    strokes = [{"char": "a", "ms": 10.0, "correct": True}, _k("r", "e")]
    got = analysis.keystroke_confusions([_instrumented("k1", strokes)])
    assert got["skipped_no_expected"] == 1
    assert got["keystrokes_considered"] == 1
    assert got["total_errors"] == 1


def test_keystroke_confusions_empty():
    got = analysis.keystroke_confusions([])
    assert got["pairs"] == []
    assert got["total_errors"] == 0
    assert got["attempts_with_expected"] == 0


def test_keystroke_character_errors_rates_and_ordering():
    strokes = [_k("r", "e"), _k("e", "e"), _k("x", "a"), _k("a", "a"), _k("a", "a")]
    got = analysis.keystroke_character_errors([_instrumented("k1", strokes)])
    by_char = {r["char"]: r for r in got["characters"]}
    assert by_char["e"] == {"char": "e", "seen": 2, "mistyped": 1, "error_rate": 0.5}
    assert by_char["a"] == {"char": "a", "seen": 3, "mistyped": 1, "error_rate": 0.3333}
    # worst rate first
    assert got["characters"][0]["char"] == "e"


def test_keystroke_character_errors_empty():
    assert analysis.keystroke_character_errors([]) == {
        "characters": [],
        "characters_seen": 0,
    }
