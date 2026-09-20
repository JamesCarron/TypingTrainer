"""analysis.py -- pure post-session analysis over the attempt store.

Written 2026-09-19 for the "analysis engine" stream of the UI refresh
(docs/UI_Refresh_Notes.md, Proposal C). Every function here is a pure function
of the ``(key, record)`` pairs ``history.iter_attempts`` returns, or the
``(key, record, keystrokes)`` triples ``history.iter_keystroke_attempts``
returns -- except ``full_report``, which is the only function that touches the
store. No UI, no HTTP, no printing, standard library only.

Alignment used everywhere a target line is compared against what was typed is
the same **positional** alignment as ``scoring.compare_lines``: characters are
compared index by index (``itertools.zip_longest``-style), not by edit
distance. This is deliberate -- it is the scoring semantics the rest of the
app already uses -- but it has a known failure mode: a single inserted or
deleted character shifts every character after it by one position, so a
one-character typo can look like a whole tail of the line being wrong. Where
that would silently inflate a count, the affected functions skip records
whose length differs too much from the target and report how many they
skipped (``skipped_length_mismatch``), rather than pretending the alignment is
sound for every record.

Old records are messy (see AGENTS.md and docs/UI_Refresh_Notes.md): three have
no "Length" (this module never reads that field -- ``len(Answer)`` is used
instead, which sidesteps the problem entirely), some have an unformatted
``EventTime`` (the literal unsubstituted f-string from a pre-refactor bug),
some have no "Passed", and none have keystrokes. Every function here parses
defensively and counts what it could not use rather than raising or silently
dropping it -- look for a ``skipped_*`` key in each function's return value.

Verified by tests/test_analysis.py.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from itertools import zip_longest

from . import history

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

#: How much an attempt's length may differ from its target line before the
#: positional alignment is considered too unreliable to use. A couple of
#: characters (one inserted/deleted character plus slack) is the brief's own
#: suggestion.
_MAX_LEN_DIFF = 2

#: A words-per-minute figure above this is not a human typing, it is a corrupt
#: record. Found in the real history on 2026-09-19: one attempt stored 1236 wpm
#: with an empty ``user_input``, an accuracy of 0.0 and a suspiciously round
#: 1.0 s duration -- internally inconsistent, and produced by a code path that
#: no longer exists. Left in the store (nothing here rewrites history) but kept
#: out of the aggregates, because one such row sets a fake personal best and
#: flattens every chart drawn to the same scale. The threshold is deliberately
#: far above any real typist: the world record is around 300 wpm.
_MAX_PLAUSIBLE_WPM = 300.0


def _implausible(record: dict) -> bool:
    """True when a record's own fields contradict each other badly enough to exclude it.

    Only used for the aggregate and charting functions. The weak-point analyses
    have their own guard (``_usable_for_alignment``) and do not read Wpm at all.
    """
    wpm = record.get("Wpm")
    if wpm is not None and wpm > _MAX_PLAUSIBLE_WPM:
        return True
    duration = record.get("Duration")
    if duration is not None and duration <= 0:
        return True
    return False

_QUOTE_CHARS = set("'\"`‘’“”")
_SPACE_CHARS = set(" \t")


def _classify_char(ch: str) -> str:
    """Bucket one character for the error-category breakdown.

    Buckets: lower, upper, digit, space, quote (quotes and apostrophes,
    checked before punctuation since an apostrophe is also punctuation),
    punct (everything else non-alphanumeric), other (anything not covered,
    e.g. non-ASCII letters -- kept so nothing is silently dropped).
    """
    if ch in _SPACE_CHARS:
        return "space"
    if ch in _QUOTE_CHARS:
        return "quote"
    if ch.isdigit():
        return "digit"
    if ch.isalpha():
        return "upper" if ch.isupper() else "lower"
    if not ch.isalnum():
        return "punct"
    return "other"


def _answer_and_input(record: dict) -> tuple[str, str] | None:
    """Pull (Answer, user_input) out of a record, or None if either is absent."""
    answer = record.get("Answer")
    typed = record.get("user_input")
    if answer is None or typed is None:
        return None
    return answer, typed


def _aligned_pairs(answer: str, typed: str):
    """Yield (target_char_or_None, typed_char_or_None) pairs, positionally."""
    return zip_longest(answer, typed, fillvalue=None)


def _usable_for_alignment(answer: str, typed: str, max_len_diff: int = _MAX_LEN_DIFF) -> bool:
    return abs(len(answer) - len(typed)) <= max_len_diff


def _parse_event_time(value) -> datetime | None:
    """Parse the ``EventTime`` field, defensively.

    New records store ``"%d-%m-%Y %H:%M:%S"``. Some legacy records carry the
    literal, never-substituted f-string ``"{self.time_start:%d-%m-%Y
    %H:%M:%S}"`` from a pre-refactor bug -- that and anything else unparsable
    returns None rather than raising.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%d-%m-%Y %H:%M:%S")
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _round(x, nd=3):
    return round(x, nd) if x is not None else None


def _mean(values):
    return statistics.fmean(values) if values else None


def _median(values):
    return statistics.median(values) if values else None


def _keystroke_deltas(keystrokes: list) -> list:
    """(prev_char, char, delta_ms) for consecutive keystrokes in one attempt.

    ``ms`` on each keystroke is measured from the first keypress of the line
    (cumulative), not a per-key delta, so the gap that actually matters --
    time since the *previous* key -- is computed here. The first keystroke of
    a line has no previous key to compare to and is excluded.
    """
    out = []
    for prev, cur in zip(keystrokes, keystrokes[1:]):
        if prev.get("ms") is None or cur.get("ms") is None:
            continue
        delta = cur["ms"] - prev["ms"]
        if delta < 0:
            continue  # malformed/out-of-order timing; not trustworthy
        out.append((prev.get("char"), cur.get("char"), delta))
    return out


# ---------------------------------------------------------------------------
# 1. WEAK POINTS
# ---------------------------------------------------------------------------


def confusion_pairs(attempts: list, max_len_diff: int = _MAX_LEN_DIFF) -> dict:
    """Rank (intended, typed) character substitutions: "you type r for e, 14 times".

    Aligns each record's Answer against its user_input positionally (see
    module docstring) and counts every position where they differ and both
    sides have a character. Records without Answer/user_input, or whose
    length differs from the target by more than ``max_len_diff``, are
    skipped and counted separately, because a length mismatch shifts the
    whole tail of the line and would otherwise inflate every pair count
    after the first insertion/deletion.
    """
    counts: Counter = Counter()
    skipped_missing = 0
    skipped_length = 0
    considered = 0
    for _key, record in attempts:
        pair = _answer_and_input(record)
        if pair is None:
            skipped_missing += 1
            continue
        answer, typed = pair
        if not _usable_for_alignment(answer, typed, max_len_diff):
            skipped_length += 1
            continue
        considered += 1
        for a, t in _aligned_pairs(answer, typed):
            if a is None or t is None:
                continue
            if a != t:
                counts[(a, t)] += 1
    ranked = [
        {"intended": a, "typed": t, "count": n}
        for (a, t), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "pairs": ranked,
        "attempts_considered": considered,
        "skipped_missing_fields": skipped_missing,
        "skipped_length_mismatch": skipped_length,
    }


def character_error_rates(attempts: list, max_len_diff: int = _MAX_LEN_DIFF) -> dict:
    """Per target character: times seen, times mistyped, error rate.

    Feeds the keyboard heatmap. Uses the same positional alignment and the
    same length-mismatch skip as ``confusion_pairs``, for the same reason.
    """
    seen: Counter = Counter()
    wrong: Counter = Counter()
    skipped_missing = 0
    skipped_length = 0
    considered = 0
    for _key, record in attempts:
        pair = _answer_and_input(record)
        if pair is None:
            skipped_missing += 1
            continue
        answer, typed = pair
        if not _usable_for_alignment(answer, typed, max_len_diff):
            skipped_length += 1
            continue
        considered += 1
        for i, a in enumerate(answer):
            seen[a] += 1
            t = typed[i] if i < len(typed) else None
            if t != a:
                wrong[a] += 1
    rows = [
        {
            "char": ch,
            "seen": n,
            "mistyped": wrong.get(ch, 0),
            "error_rate": _round(wrong.get(ch, 0) / n) if n else 0.0,
        }
        for ch, n in seen.items()
    ]
    rows.sort(key=lambda r: (-r["error_rate"], -r["seen"]))
    return {
        "characters": rows,
        "attempts_considered": considered,
        "skipped_missing_fields": skipped_missing,
        "skipped_length_mismatch": skipped_length,
    }


def problem_words(attempts: list, max_len_diff: int = _MAX_LEN_DIFF, top_n: int = 50) -> dict:
    """Which words in the book get mistyped most, with an example mistake.

    A "word" is a whitespace-separated run of the target line. Because the
    alignment is positional, a word is judged mistyped if the substring of
    user_input at the same character offsets differs from it -- so this
    shares the same length-mismatch skip and the same limitation as
    ``confusion_pairs``.
    """
    counts: Counter = Counter()
    examples: dict[str, str] = {}
    skipped_missing = 0
    skipped_length = 0
    considered = 0
    for _key, record in attempts:
        pair = _answer_and_input(record)
        if pair is None:
            skipped_missing += 1
            continue
        answer, typed = pair
        if not _usable_for_alignment(answer, typed, max_len_diff):
            skipped_length += 1
            continue
        considered += 1
        offset = 0
        for word in answer.split(" "):
            start, end = offset, offset + len(word)
            offset = end + 1  # + the space we split on
            if not word:
                continue
            typed_slice = typed[start:end]
            if typed_slice != word:
                counts[word] += 1
                examples.setdefault(word, typed_slice if typed_slice else "(nothing typed)")
    ranked = [
        {"word": w, "count": n, "example_typed": examples.get(w, "")}
        for w, n in counts.most_common(top_n)
    ]
    return {
        "words": ranked,
        "attempts_considered": considered,
        "skipped_missing_fields": skipped_missing,
        "skipped_length_mismatch": skipped_length,
    }


def error_categories(attempts: list, max_len_diff: int = _MAX_LEN_DIFF) -> dict:
    """Error rate split by character class: lower/upper/digit/quote/punct/space.

    Answers the "fine on letters but loses every line on semicolons" question.
    Same alignment and skip rule as the other weak-point functions.
    """
    seen: Counter = Counter()
    wrong: Counter = Counter()
    skipped_missing = 0
    skipped_length = 0
    considered = 0
    for _key, record in attempts:
        pair = _answer_and_input(record)
        if pair is None:
            skipped_missing += 1
            continue
        answer, typed = pair
        if not _usable_for_alignment(answer, typed, max_len_diff):
            skipped_length += 1
            continue
        considered += 1
        for i, a in enumerate(answer):
            cat = _classify_char(a)
            seen[cat] += 1
            t = typed[i] if i < len(typed) else None
            if t != a:
                wrong[cat] += 1
    categories = ["lower", "upper", "digit", "quote", "punct", "space", "other"]
    rows = [
        {
            "category": cat,
            "seen": seen.get(cat, 0),
            "mistyped": wrong.get(cat, 0),
            "error_rate": _round(wrong.get(cat, 0) / seen[cat]) if seen.get(cat) else 0.0,
        }
        for cat in categories
        if seen.get(cat, 0) > 0
    ]
    rows.sort(key=lambda r: -r["error_rate"])
    return {
        "categories": rows,
        "attempts_considered": considered,
        "skipped_missing_fields": skipped_missing,
        "skipped_length_mismatch": skipped_length,
    }


def correction_rate(attempts: list) -> dict:
    """How much was typed and thrown away, from user_input_full vs user_input.

    ``user_input_full`` holds every character typed, including ones later
    deleted; ``user_input`` is what was finally submitted. The excess length
    of the full field over the submitted one is used as a proxy for
    "characters typed then backspaced" -- it undercounts when a backspace was
    immediately followed by retyping the *same* character (the lengths can
    still work out close), but it needs no keystroke data, which is the
    point of this function. Records with no ``user_input_full`` (every
    pre-instrumentation record duplicates it from user_input, but a record
    missing the field entirely is skipped) are counted separately.
    """
    per_attempt = []
    skipped_missing = 0
    total_extra = 0
    total_full = 0
    for key, record in attempts:
        full = record.get("user_input_full")
        submitted = record.get("user_input")
        if full is None or submitted is None:
            skipped_missing += 1
            continue
        extra = max(0, len(full) - len(submitted))
        rate = extra / len(full) if len(full) else 0.0
        per_attempt.append({"key": key, "extra_chars": extra, "correction_rate": _round(rate)})
        total_extra += extra
        total_full += len(full)
    overall = _round(total_extra / total_full) if total_full else 0.0
    return {
        "overall_correction_rate": overall,
        "total_extra_chars": total_extra,
        "per_attempt": per_attempt,
        "attempts_considered": len(per_attempt),
        "skipped_missing_fields": skipped_missing,
    }


def keystroke_confusions(instrumented: list) -> dict:
    """Rank (intended, typed) substitutions from the keystrokes, corrections included.

    This is the honest version of ``confusion_pairs``, and on a store built
    under a strict accuracy criterion it is the only one with anything to
    work with. ``confusion_pairs`` can only see mistakes that survived into
    the submitted line, and a typist who retypes until the line passes never
    submits one: measured on the real history on 2026-09-19, 209 attempts and
    20,566 characters yielded eight visible errors. Every mistake the typist
    actually made is here instead -- including the ones they backspaced over
    and, in stop-on-error mode, the ones that were refused outright.

    Needs the ``expected`` field, recorded from 2026-09-19. Keystrokes
    without it are counted in ``skipped_no_expected`` rather than guessed at:
    the expected character cannot be reconstructed after the fact, because
    backspaces are not part of the record and the position at any given press
    is therefore ambiguous.
    """
    counts: Counter = Counter()
    skipped = 0
    considered = 0
    attempts_used = 0
    for _key, _record, keystrokes in instrumented:
        used_this_attempt = False
        for stroke in keystrokes:
            expected = stroke.get("expected")
            char = stroke.get("char")
            if expected is None or char is None:
                skipped += 1
                continue
            considered += 1
            used_this_attempt = True
            if char != expected:
                counts[(expected, char)] += 1
        if used_this_attempt:
            attempts_used += 1
    pairs = [
        {"intended": intended, "typed": typed, "count": count}
        for (intended, typed), count in counts.most_common()
    ]
    return {
        "pairs": pairs,
        "total_errors": sum(counts.values()),
        "keystrokes_considered": considered,
        "attempts_with_expected": attempts_used,
        "skipped_no_expected": skipped,
    }


def keystroke_character_errors(instrumented: list) -> dict:
    """Per intended character: times attempted, times mistyped, error rate.

    Same source and the same caveat as ``keystroke_confusions``: this counts
    what the fingers did, not what the submitted line ended up saying, so it
    sees the corrected mistakes too. The keyboard heatmap should prefer this
    over the submitted-text version once there is data in it.
    """
    seen: Counter = Counter()
    wrong: Counter = Counter()
    for _key, _record, keystrokes in instrumented:
        for stroke in keystrokes:
            expected = stroke.get("expected")
            char = stroke.get("char")
            if expected is None or char is None:
                continue
            seen[expected] += 1
            if char != expected:
                wrong[expected] += 1
    rows = [
        {
            "char": ch,
            "seen": n,
            "mistyped": wrong.get(ch, 0),
            "error_rate": _round(wrong.get(ch, 0) / n, 4) if n else 0.0,
        }
        for ch, n in seen.items()
    ]
    rows.sort(key=lambda r: (-r["error_rate"], -r["seen"], r["char"]))
    return {"characters": rows, "characters_seen": len(rows)}


# ---------------------------------------------------------------------------
# 2. SPEED (needs keystroke timing; degrades gracefully without it)
# ---------------------------------------------------------------------------


def key_latencies(instrumented: list) -> dict:
    """Per character: count, mean and median ms since the previous keystroke.

    Ranked slowest (by mean) first. The first keystroke of every line is
    excluded -- there is no previous key in that line to measure a gap from.
    """
    by_char: dict[str, list] = defaultdict(list)
    for _key, _record, keystrokes in instrumented:
        for _prev_char, char, delta in _keystroke_deltas(keystrokes):
            if char is not None:
                by_char[char].append(delta)
    rows = [
        {
            "char": ch,
            "count": len(deltas),
            "mean_ms": _round(_mean(deltas), 1),
            "median_ms": _round(_median(deltas), 1),
        }
        for ch, deltas in by_char.items()
    ]
    rows.sort(key=lambda r: -r["mean_ms"])
    return {"keys": rows, "instrumented_attempts": len(instrumented)}


def bigram_latencies(instrumented: list, min_occurrences: int = 5) -> dict:
    """Per (previous char, char) transition: count, mean and median ms.

    Ranked slowest first, with ``min_occurrences`` as a floor so a single
    slow outlier cannot top the list. This is the headline speed output --
    the brief's "your personal slow transitions are what cost you".
    """
    by_pair: dict[tuple, list] = defaultdict(list)
    for _key, _record, keystrokes in instrumented:
        for prev_char, char, delta in _keystroke_deltas(keystrokes):
            if prev_char is not None and char is not None:
                by_pair[(prev_char, char)].append(delta)
    rows = [
        {
            "prev": p,
            "char": c,
            "count": len(deltas),
            "mean_ms": _round(_mean(deltas), 1),
            "median_ms": _round(_median(deltas), 1),
        }
        for (p, c), deltas in by_pair.items()
        if len(deltas) >= min_occurrences
    ]
    rows.sort(key=lambda r: -r["mean_ms"])
    return {
        "bigrams": rows,
        "min_occurrences": min_occurrences,
        "instrumented_attempts": len(instrumented),
    }


#: Standard touch-typing home-row finger assignment for a QWERTY layout.
#: Left hand fingers 1-4 = pinky..index, right hand 5-8 = index..pinky.
#: Thumbs (space) are their own bucket. This is the conventional 10-finger
#: touch-typing chart, not derived from any user's actual data, and it
#: assumes QWERTY -- it will misclassify every key on any other layout.
QWERTY_FINGER_MAP: dict[str, str] = {
    **{c: "L-pinky" for c in "q a z 1 ! Q A Z".split()},
    **{c: "L-ring" for c in "w s x 2 @ W S X".split()},
    **{c: "L-middle" for c in "e d c 3 # E D C".split()},
    **{c: "L-index" for c in "r f v t g b 4 5 $ % R F V T G B".split()},
    **{c: "R-index" for c in "y h n u j m 6 7 ^ & Y H N U J M".split()},
    **{c: "R-middle" for c in "i k , 8 * I K".split()},
    **{c: "R-ring" for c in "o l . 9 ( O L".split()},
    **{c: "R-pinky" for c in "p ; / 0 ) - _ = + [ ] { } \\ | ' \" P".split()},
    " ": "thumb",
}


def _finger_for(ch: str | None) -> str | None:
    if ch is None:
        return None
    return QWERTY_FINGER_MAP.get(ch)


def same_finger_bigrams(instrumented: list, min_occurrences: int = 5) -> dict:
    """Transitions between two different keys typed with the same QWERTY finger.

    These are the mechanically slow transitions -- a lateral reach without
    the other fingers to help. Repeated *same* key ("ll") is excluded on
    purpose: that is a different phenomenon (a key repeat, usually fast),
    not the same-finger-different-key reach this is meant to surface.
    Requires a keyboard-position finger map (``QWERTY_FINGER_MAP`` above,
    the standard home-row assignment), so it assumes QWERTY and cannot
    classify characters outside that map (digits/symbols on some layouts,
    or anything typed with a modifier this map does not know about).
    """
    same_finger: dict[tuple, list] = defaultdict(list)
    all_deltas = []
    for _key, _record, keystrokes in instrumented:
        for prev_char, char, delta in _keystroke_deltas(keystrokes):
            if prev_char is None or char is None:
                continue
            all_deltas.append(delta)
            if prev_char == char:
                continue
            f1, f2 = _finger_for(prev_char), _finger_for(char)
            if f1 is not None and f1 == f2:
                same_finger[(prev_char, char)].append(delta)
    rows = [
        {
            "prev": p,
            "char": c,
            "finger": _finger_for(p),
            "count": len(deltas),
            "mean_ms": _round(_mean(deltas), 1),
            "median_ms": _round(_median(deltas), 1),
        }
        for (p, c), deltas in same_finger.items()
        if len(deltas) >= min_occurrences
    ]
    rows.sort(key=lambda r: -r["mean_ms"])
    same_finger_all = [d for deltas in same_finger.values() for d in deltas]
    return {
        "pairs": rows,
        "min_occurrences": min_occurrences,
        "same_finger_mean_ms": _round(_mean(same_finger_all), 1),
        "all_bigrams_mean_ms": _round(_mean(all_deltas), 1),
        "instrumented_attempts": len(instrumented),
    }


def rhythm(instrumented: list, stall_ms: float = 500.0) -> dict:
    """Consistency of typing rhythm: mean/stdev of inter-key gaps, and stalls.

    A stall is any inter-key gap over ``stall_ms``; both the count and the
    (attempt key, position, char) of each are returned, since where you
    hesitate in a line is itself a finding, not just how often.
    """
    all_deltas = []
    per_attempt = []
    stalls = []
    for key, _record, keystrokes in instrumented:
        deltas = [d for _p, _c, d in _keystroke_deltas(keystrokes)]
        all_deltas.extend(deltas)
        attempt_stdev = statistics.pstdev(deltas) if len(deltas) >= 2 else 0.0
        per_attempt.append(
            {
                "key": key,
                "mean_ms": _round(_mean(deltas), 1),
                "stdev_ms": _round(attempt_stdev, 1),
                "n_keys": len(deltas),
            }
        )
        for i, (_prev_char, char, delta) in enumerate(_keystroke_deltas(keystrokes)):
            if delta > stall_ms:
                stalls.append({"key": key, "position": i + 1, "char": char, "gap_ms": _round(delta, 1)})
    return {
        "mean_ms": _round(_mean(all_deltas), 1),
        "stdev_ms": _round(statistics.pstdev(all_deltas), 1) if len(all_deltas) >= 2 else 0.0,
        "stall_threshold_ms": stall_ms,
        "stall_count": len(stalls),
        "stalls": stalls,
        "per_attempt": per_attempt,
        "instrumented_attempts": len(instrumented),
    }


def error_timing(instrumented: list) -> dict:
    """Are wrong keystrokes preceded by a longer-than-usual gap?

    Compares the mean gap before an incorrect keystroke to the mean gap
    before a correct one. A gap noticeably longer before errors than before
    correct keys suggests "does not know the key" (hesitating and still
    getting it wrong); gaps about the same suggests "going too fast" instead
    (the error is not preceded by any extra thinking time). Keystrokes whose
    ``correct`` flag is None (not recorded) are excluded from both sides.
    """
    before_error = []
    before_correct = []
    for _key, _record, keystrokes in instrumented:
        for prev, cur in zip(keystrokes, keystrokes[1:]):
            if prev.get("ms") is None or cur.get("ms") is None:
                continue
            delta = cur["ms"] - prev["ms"]
            if delta < 0:
                continue
            correct = cur.get("correct")
            if correct is True:
                before_correct.append(delta)
            elif correct is False:
                before_error.append(delta)
    mean_error = _mean(before_error)
    mean_correct = _mean(before_correct)
    if mean_error is None or mean_correct is None:
        interpretation = "insufficient data"
    elif mean_error > mean_correct * 1.15:
        interpretation = "errors follow longer pauses: looks like unfamiliarity with the key"
    elif mean_error < mean_correct * 0.85:
        interpretation = "errors follow shorter pauses: looks like going too fast"
    else:
        interpretation = "no clear difference: gap before errors is about the same as before correct keys"
    return {
        "mean_gap_before_error_ms": _round(mean_error, 1),
        "mean_gap_before_correct_ms": _round(mean_correct, 1),
        "n_errors_with_timing": len(before_error),
        "n_correct_with_timing": len(before_correct),
        "interpretation": interpretation,
        "instrumented_attempts": len(instrumented),
    }


# ---------------------------------------------------------------------------
# 3. PROGRESS
# ---------------------------------------------------------------------------


def learning_curve(attempts: list, window: int = 10) -> dict:
    """WPM and accuracy per attempt over time, plus a rolling mean, for charting.

    ``attempts`` is trusted to already be oldest-first, matching
    ``history.iter_attempts``'s contract; this does not re-sort by
    ``EventTime`` (some of which cannot even be parsed -- see module
    docstring). Attempts missing Wpm or Accuracy are skipped and counted, as
    are implausible ones (see ``_implausible``) -- a single corrupt 1236 wpm
    row otherwise squashes the whole curve against the axis.
    """
    points = []
    skipped = 0
    implausible = 0
    wpm_window: list = []
    acc_window: list = []
    for key, record in attempts:
        wpm = record.get("Wpm")
        acc = record.get("Accuracy")
        if wpm is None or acc is None:
            skipped += 1
            continue
        if _implausible(record):
            implausible += 1
            continue
        wpm_window.append(wpm)
        acc_window.append(acc)
        if len(wpm_window) > window:
            wpm_window.pop(0)
        if len(acc_window) > window:
            acc_window.pop(0)
        points.append(
            {
                "key": key,
                "wpm": wpm,
                "accuracy": acc,
                "rolling_mean_wpm": _round(_mean(wpm_window), 2),
                "rolling_mean_accuracy": _round(_mean(acc_window), 4),
            }
        )
    return {
        "points": points,
        "window": window,
        "skipped_missing_fields": skipped,
        "skipped_implausible": implausible,
    }


def attempts_per_line(attempts: list) -> dict:
    """How many attempts each line of the book took; identifies the walls.

    Lines are identified by their target text (``Answer``), not by
    ``LineIndex``, so a re-numbering of the book (or a legacy record that
    never carried an index) does not fragment the count. Records with no
    ``Answer`` are skipped and counted.
    """
    counts: Counter = Counter()
    passed_counts: Counter = Counter()
    skipped = 0
    for _key, record in attempts:
        answer = record.get("Answer")
        if answer is None:
            skipped += 1
            continue
        counts[answer] += 1
        if record.get("Passed"):
            passed_counts[answer] += 1
    rows = [
        {
            "line": line,
            "attempts": n,
            "passed": passed_counts.get(line, 0),
        }
        for line, n in counts.items()
    ]
    rows.sort(key=lambda r: -r["attempts"])
    return {"lines": rows, "skipped_missing_fields": skipped}


def daily_activity(attempts: list) -> dict:
    """Attempts, time typing and mean WPM per calendar day, for a practice calendar.

    Days come from parsing ``EventTime`` (see ``_parse_event_time``); records
    whose EventTime cannot be parsed are skipped and counted, not guessed at.
    """
    by_day: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "duration": 0.0, "wpms": []})
    skipped = 0
    for _key, record in attempts:
        when = _parse_event_time(record.get("EventTime"))
        if when is None:
            skipped += 1
            continue
        day = when.date().isoformat()
        bucket = by_day[day]
        bucket["attempts"] += 1
        bucket["duration"] += record.get("Duration") or 0.0
        if record.get("Wpm") is not None:
            bucket["wpms"].append(record["Wpm"])
    days = [
        {
            "date": day,
            "attempts": b["attempts"],
            "duration_s": _round(b["duration"], 1),
            "mean_wpm": _round(_mean(b["wpms"]), 2),
        }
        for day, b in sorted(by_day.items())
    ]
    return {"days": days, "skipped_unparsable_event_time": skipped}


def session_summary(attempts: list) -> dict:
    """Summary tiles for one session's worth of attempts.

    ``attempts`` is the whole session: the caller either passes a
    time-bounded slice of ``iter_attempts`` (e.g. everything since the app
    was last opened) or groups by a gap threshold itself -- this function
    makes no assumption about how the slice was chosen and simply summarises
    whatever list it is given, in the order given.
    """
    lines_completed = 0
    passed = 0
    failed = 0
    duration = 0.0
    wpms = []
    accuracies = []
    scored_lines = []
    for key, record in attempts:
        if record.get("Answer") is None:
            continue
        lines_completed += 1
        duration += record.get("Duration") or 0.0
        if record.get("Passed") is True:
            passed += 1
        elif record.get("Passed") is False:
            failed += 1
        wpm = record.get("Wpm")
        if wpm is not None:
            wpms.append(wpm)
            scored_lines.append({"key": key, "line": record.get("Answer"), "wpm": wpm})
        if record.get("Accuracy") is not None:
            accuracies.append(record["Accuracy"])
    best = max(scored_lines, key=lambda r: r["wpm"], default=None)
    worst = min(scored_lines, key=lambda r: r["wpm"], default=None)
    return {
        "lines_completed": lines_completed,
        "passed": passed,
        "failed": failed,
        "duration_s": _round(duration, 1),
        "mean_wpm": _round(_mean(wpms), 2),
        "best_wpm": _round(max(wpms), 2) if wpms else None,
        "mean_accuracy": _round(_mean(accuracies), 4),
        "best_line": best,
        "worst_line": worst,
    }


def overall_stats(attempts: list, today: date | None = None) -> dict:
    """All-time tiles: totals, top/mean WPM and accuracy, current/longest streak.

    Streaks are computed from calendar days with at least one attempt (via
    ``daily_activity``). ``today`` defaults to ``date.today()`` and is only
    used to decide whether the most recent active day still counts as an
    unbroken "current" streak (an idle day breaks it); pass it explicitly in
    tests instead of relying on the wall clock.

    Records whose own fields contradict each other are excluded from the
    speed and accuracy figures and counted in ``excluded_implausible``; see
    ``_implausible``. ``total_attempts`` still counts every attempt, because
    the user did type them.
    """
    today = today or date.today()
    usable = [(k, r) for k, r in attempts if not _implausible(r)]
    excluded = len(attempts) - len(usable)
    wpms = [r.get("Wpm") for _k, r in usable if r.get("Wpm") is not None]
    accuracies = [r.get("Accuracy") for _k, r in usable if r.get("Accuracy") is not None]
    total_duration = sum(r.get("Duration") or 0.0 for _k, r in usable)

    days_info = daily_activity(attempts)
    active_days = sorted(date.fromisoformat(d["date"]) for d in days_info["days"])
    longest = current = 0
    if active_days:
        longest = 1
        run = 1
        for prev, cur in zip(active_days, active_days[1:]):
            if (cur - prev).days == 1:
                run += 1
            else:
                run = 1
            longest = max(longest, run)
        # current streak: walk back from the most recent active day, but only
        # if that day is today or yesterday -- otherwise the streak is over.
        last_active = active_days[-1]
        if (today - last_active).days <= 1:
            current = 1
            for i in range(len(active_days) - 1, 0, -1):
                if (active_days[i] - active_days[i - 1]).days == 1:
                    current += 1
                else:
                    break

    return {
        "total_attempts": len(attempts),
        "total_duration_s": _round(total_duration, 1),
        "top_wpm": _round(max(wpms), 2) if wpms else None,
        "mean_wpm": _round(_mean(wpms), 2),
        "top_accuracy": _round(max(accuracies), 4) if accuracies else None,
        "mean_accuracy": _round(_mean(accuracies), 4),
        "current_streak_days": current,
        "longest_streak_days": longest,
        "active_days": len(active_days),
        "excluded_implausible": excluded,
    }


# ---------------------------------------------------------------------------
# 4. THE REVIEW SCREEN (session deltas and the one recommended next action)
# ---------------------------------------------------------------------------

#: The gap, in minutes, that separates one session from the next. Must agree
#: with ``web.server.SESSION_GAP`` (currently ``timedelta(minutes=30)``) --
#: kept as an independent constant rather than an import because server.py
#: imports this module, not the other way around, and analysis.py must stay
#: free of any web-layer dependency. If the two ever diverge that is a bug
#: to fix by editing both, not a reason to import across the boundary.
SESSION_GAP_MINUTES = 30


def _split_into_sessions(attempts: list, gap_minutes: float = SESSION_GAP_MINUTES) -> list:
    """Split oldest-first ``(key, record)`` pairs into runs (sessions).

    A new session starts wherever the gap between two consecutive
    ``EventTime`` values exceeds ``gap_minutes``, or wherever either time
    cannot be parsed at all -- the same rule
    ``web.server._current_session_attempts`` uses for finding the single
    most-recent session, generalised here to split the whole history rather
    than just look backward from the end.
    """
    if not attempts:
        return []
    sessions = [[attempts[0]]]
    threshold = timedelta(minutes=gap_minutes)
    for i in range(1, len(attempts)):
        prev_t = _parse_event_time(attempts[i - 1][1].get("EventTime"))
        cur_t = _parse_event_time(attempts[i][1].get("EventTime"))
        if prev_t is None or cur_t is None or (cur_t - prev_t) > threshold:
            sessions.append([])
        sessions[-1].append(attempts[i])
    return sessions


def _delta_field(current, previous) -> dict:
    """One {"current", "previous", "delta", "direction"} entry for session_deltas.

    ``direction`` is "up"/"down"/"same" when both figures are present, and
    None when either is missing -- a missing previous figure (first-ever
    session) must never be silently treated as zero, which would show as a
    dishonestly huge "improvement".
    """
    if current is None or previous is None:
        return {"current": current, "previous": previous, "delta": None, "direction": None}
    delta = _round(current - previous, 4)
    direction = "up" if current > previous else "down" if current < previous else "same"
    return {"current": current, "previous": previous, "delta": delta, "direction": direction}


def _worst_category_delta(cur_cats: dict, prev_cats: dict | None) -> dict:
    """Compare the current session's single worst error category to its own
    rate last session (not to whatever was worst last session, which might be
    a different category entirely -- the brief asks whether *the* worst
    category improved, which only makes sense read against its own history).
    """
    # Only a category the typist actually got wrong can be "the worst" one.
    # Taking the first row regardless produced "lower is your worst category
    # at 0.0%" on real data, because within a single session every rate ties
    # at zero and the tie-break then picks alphabetically -- a confident
    # statement about nothing. With no errors at all we decline to name one.
    cur_rows = [
        r
        for r in cur_cats.get("categories", [])
        if r.get("mistyped", 0) > 0 and r.get("error_rate", 0) > 0
    ]
    cur_rows.sort(key=lambda r: (-r["error_rate"], r["category"]))
    worst = cur_rows[0] if cur_rows else None
    if worst is None:
        return {"category": None, "current_rate": None, "previous_rate": None, "direction": None}
    category = worst["category"]
    current_rate = worst["error_rate"]
    previous_rate = None
    if prev_cats:
        prev_by_cat = {r["category"]: r["error_rate"] for r in prev_cats.get("categories", [])}
        previous_rate = prev_by_cat.get(category)
    if previous_rate is None:
        direction = None
    elif current_rate < previous_rate:
        direction = "improved"
    elif current_rate > previous_rate:
        direction = "worse"
    else:
        direction = "unchanged"
    return {
        "category": category,
        "current_rate": current_rate,
        "previous_rate": previous_rate,
        "direction": direction,
    }


def _empty_session_deltas() -> dict:
    empty = {"current": None, "previous": None, "delta": None, "direction": None}
    return {
        "has_previous": False,
        "wpm": dict(empty),
        "accuracy": dict(empty),
        "lines_completed": dict(empty),
        "time_typing_s": dict(empty),
        "worst_category": {"category": None, "current_rate": None, "previous_rate": None, "direction": None},
    }


def session_deltas(attempts: list) -> dict:
    """What moved between the session just finished and the one before it.

    ``attempts`` is the whole history relevant to the comparison -- every
    attempt of the session just finished, plus the history before it -- oldest
    first, exactly as ``history.iter_attempts()`` returns it. This function
    does its own session splitting (``_split_into_sessions``, using
    ``SESSION_GAP_MINUTES`` -- see that constant's docstring for why it is
    not imported from ``web.server``): the last session found is "this
    session", the one immediately before it is "last session", and anything
    older is not used.

    Returns a dict with ``has_previous`` plus five comparisons:
    ``wpm`` and ``accuracy`` (session means), ``lines_completed`` and
    ``time_typing_s`` (session totals) as ``{"current", "previous", "delta",
    "direction"}``, and ``worst_category`` (see ``_worst_category_delta``)
    for whether the session's single worst error category improved, stayed
    the same or got worse against its own rate last session.

    Never raises. An empty ``attempts`` list, or a history that is all one
    session so far (no previous session to compare against), both return a
    fully-shaped result with ``has_previous: False`` and every comparison's
    "previous"/"delta"/"direction" as None -- "not enough data yet" is a
    normal answer here, not an error.
    """
    sessions = _split_into_sessions(attempts)
    if not sessions:
        return _empty_session_deltas()

    current = sessions[-1]
    previous = sessions[-2] if len(sessions) >= 2 else []

    cur_summary = session_summary(current)
    cur_cats = error_categories(current)
    if not previous:
        return {
            "has_previous": False,
            "wpm": _delta_field(cur_summary.get("mean_wpm"), None),
            "accuracy": _delta_field(cur_summary.get("mean_accuracy"), None),
            "lines_completed": _delta_field(cur_summary.get("lines_completed"), None),
            "time_typing_s": _delta_field(cur_summary.get("duration_s"), None),
            "worst_category": _worst_category_delta(cur_cats, None),
        }

    prev_summary = session_summary(previous)
    prev_cats = error_categories(previous)
    return {
        "has_previous": True,
        "wpm": _delta_field(cur_summary.get("mean_wpm"), prev_summary.get("mean_wpm")),
        "accuracy": _delta_field(cur_summary.get("mean_accuracy"), prev_summary.get("mean_accuracy")),
        "lines_completed": _delta_field(
            cur_summary.get("lines_completed"), prev_summary.get("lines_completed")
        ),
        "time_typing_s": _delta_field(cur_summary.get("duration_s"), prev_summary.get("duration_s")),
        "worst_category": _worst_category_delta(cur_cats, prev_cats),
    }


def next_action(report: dict) -> dict:
    """One recommended next action, derived from the weak-point analysis.

    ``report`` is shaped like ``full_report()`` (or any dict carrying at
    least ``data_coverage`` and ``weak_points`` in that shape). Preference
    order, each degrading to the next when it has nothing to offer:

    1. The worst error category (``weak_points.error_categories``) -- the
       coarsest, most reliable signal, and the one the review screen's own
       example leads with ("quotes are your worst category").
    2. The worst individual character, preferring the keystroke-derived view
       (``keystroke_character_errors``) over the submitted-text one
       (``character_error_rates``) for the same reason ``drills.py`` does --
       under a strict accuracy floor the submitted text is almost always
       perfect, so real mistakes mostly only exist in the keystrokes. Noise
       floor of 3 sightings, same as ``drills._MIN_CHAR_SAMPLES``, and
       whitespace is excluded for the same alignment-artefact reason.
    3. The worst confusion pair, same keystroke-preferred fallback, floored
       at 2 occurrences.

    Returns ``{"message", "kind", "target", "detail"}``: ``kind`` is one of
    "category"/"char"/"confusion"/None, ``target`` a short JSON-safe string
    (or None), ``detail`` the underlying row this was built from (or None).
    A store with no attempts at all -- or one with attempts but no weak point
    clearing any noise floor -- returns a gentle message with ``kind: None``
    rather than raising or returning nothing.
    """
    total_attempts = report.get("data_coverage", {}).get("total_attempts", 0)
    if not total_attempts:
        return {
            "message": "Keep typing — not enough data yet.",
            "kind": None,
            "target": None,
            "detail": None,
        }

    weak_points = report.get("weak_points", {})

    cat_rows = [
        r for r in weak_points.get("error_categories", {}).get("categories", [])
        if r.get("mistyped", 0) > 0
    ]
    if cat_rows:
        worst = cat_rows[0]
        return {
            "message": (
                f"{worst['category'].capitalize()} is your worst error category at "
                f"{worst['error_rate'] * 100:.0f}% — start next time with a "
                f"{worst['category']} drill."
            ),
            "kind": "category",
            "target": worst["category"],
            "detail": worst,
        }

    char_rows = weak_points.get("keystroke_character_errors", {}).get("characters", []) or (
        weak_points.get("character_error_rates", {}).get("characters", [])
    )
    char_rows = [
        r for r in char_rows
        if r.get("seen", 0) >= 3 and r.get("mistyped", 0) > 0
        and r.get("char") not in (" ", "\t", "\n")
    ]
    if char_rows:
        worst = char_rows[0]
        return {
            "message": (
                f"'{worst['char']}' is your worst key at "
                f"{worst['error_rate'] * 100:.0f}% -- a short drill on it is next."
            ),
            "kind": "char",
            "target": worst["char"],
            "detail": worst,
        }

    confusion_rows = weak_points.get("keystroke_confusions", {}).get("pairs", []) or (
        weak_points.get("confusion_pairs", {}).get("pairs", [])
    )
    confusion_rows = [r for r in confusion_rows if r.get("count", 0) >= 2]
    if confusion_rows:
        worst = confusion_rows[0]
        return {
            "message": (
                f"You type '{worst['typed']}' when you mean '{worst['intended']}' -- "
                f"worth a drill."
            ),
            "kind": "confusion",
            "target": f"{worst['intended']}>{worst['typed']}",
            "detail": worst,
        }

    return {
        "message": "No clear weak point yet — keep typing to build up data.",
        "kind": None,
        "target": None,
        "detail": None,
    }


# ---------------------------------------------------------------------------
# 5. ENTRY POINT
# ---------------------------------------------------------------------------


def full_report(text_name: str | None = None) -> dict:
    """Read the store and run every analysis, as one JSON-serialisable dict.

    The only function in this module that touches ``history``. Everything it
    returns is JSON-safe (plain str/int/float/bool/None/list/dict -- no
    datetime objects, no Counter, no numpy), so it can go straight to
    ``json.dumps`` for ``GET /api/analysis``.
    """
    attempts = history.iter_attempts(text_name=text_name)
    instrumented = history.iter_keystroke_attempts(text_name=text_name)

    report = {
        "data_coverage": {
            "text_name": text_name,
            "total_attempts": len(attempts),
            "instrumented_attempts": len(instrumented),
        },
        "weak_points": {
            "confusion_pairs": confusion_pairs(attempts),
            # From the keystrokes, so it includes mistakes that were corrected
            # before the line was submitted. Prefer this one wherever it has data.
            "keystroke_confusions": keystroke_confusions(instrumented),
            "keystroke_character_errors": keystroke_character_errors(instrumented),
            "character_error_rates": character_error_rates(attempts),
            "problem_words": problem_words(attempts),
            "error_categories": error_categories(attempts),
            "correction_rate": correction_rate(attempts),
        },
        "speed": {
            "key_latencies": key_latencies(instrumented),
            "bigram_latencies": bigram_latencies(instrumented),
            "same_finger_bigrams": same_finger_bigrams(instrumented),
            "rhythm": rhythm(instrumented),
            "error_timing": error_timing(instrumented),
        },
        "progress": {
            "learning_curve": learning_curve(attempts),
            "attempts_per_line": attempts_per_line(attempts),
            "daily_activity": daily_activity(attempts),
            "session_summary": session_summary(attempts),
            "overall_stats": overall_stats(attempts),
        },
    }
    return report
