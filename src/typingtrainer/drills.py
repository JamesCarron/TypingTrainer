"""drills.py -- turning the analysis engine's diagnosis into practice.

Written 2026-09-19 for the "improvement loop" stream of the UI refresh
(docs/UI_Refresh_Notes.md, Proposal C, "Turning analysis into improvement").
Everything here is a pure function over the dict ``analysis.full_report()``
returns, except ``practice_plan``, which is the only function that touches
the store (via ``analysis.full_report``, ``history.get_position`` and the
text library). Standard library only, no UI, no printing, no clock reads.

Everything returned is JSON-serialisable (str/int/float/bool/None/list/dict),
matching the contract ``analysis.py`` already keeps.

Verified by tests/test_drills.py.
"""

from __future__ import annotations

import random
import statistics

from . import analysis, config, history, session, texts

# ---------------------------------------------------------------------------
# shared constants
# ---------------------------------------------------------------------------

#: A character needs to have been seen at least this many times before its
#: error rate is trusted enough to rank -- one miss out of one attempt is a
#: 100% error rate that means nothing.
_MIN_CHAR_SAMPLES = 3

#: A confusion pair needs to have happened at least twice before it is
#: treated as a pattern rather than a single slip.
_MIN_CONFUSION_COUNT = 2

#: Word bank for synthetic drills: short, common, ordinary-English words with
#: enough spread across the alphabet (including rarer letters like q/x/z)
#: that most single characters and many bigrams can be found inside at least
#: one of them. This is deliberately not a dictionary or a corpus -- it only
#: has to be big enough that a handful of weak characters and bigrams can
#: usually be found inside something that reads as a word.
_WORD_BANK = (
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
    "had", "her", "was", "one", "our", "out", "day", "get", "has", "him",
    "his", "how", "man", "new", "now", "old", "see", "two", "way", "who",
    "boy", "did", "its", "let", "put", "say", "she", "too", "use", "yes",
    "that", "with", "have", "this", "will", "your", "from", "they", "know",
    "want", "been", "good", "much", "some", "time", "very", "when", "come",
    "here", "just", "like", "long", "make", "many", "over", "such", "take",
    "than", "them", "well", "were", "what", "word", "work", "year", "back",
    "call", "came", "each", "even", "find", "give", "hand", "high", "keep",
    "kind", "last", "left", "life", "live", "look", "made", "most", "move",
    "must", "name", "need", "next", "only", "open", "part", "play", "said",
    "same", "show", "side", "tell", "turn", "used", "very", "wave", "zinc",
    "quiz", "quick", "quiet", "equal", "exact", "extra", "fixed", "vivid",
    "gravy", "juicy", "jazzy", "fuzzy", "sugar", "table", "river", "cloud",
    "brick", "dance", "eager", "habit", "ideal", "judge", "knife", "lemon",
    "mango", "noble", "oasis", "proud", "queen", "quilt", "wrist", "xerox",
    "yield", "zebra", "above", "among", "apple", "below", "could", "every",
    "first", "found", "great", "house", "large", "learn", "never", "other",
    "place", "plant", "point", "right", "small", "sound", "spell", "still",
    "study", "their", "there", "these", "thing", "think", "three", "under",
    "water", "where", "which", "world", "would", "write",
)


def _get(obj, name, default=None):
    """Read ``name`` off ``obj`` whether it is a dict or a dataclass/object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _round(x, nd=4):
    return round(x, nd) if x is not None else None


# ---------------------------------------------------------------------------
# 1. weak_targets
# ---------------------------------------------------------------------------


def weak_targets(report: dict, limit: int = 10) -> list:
    """Distil ``analysis.full_report()`` into a ranked list of things to practise.

    Three kinds of entry, each pulled from a different part of the report:

    - ``"char"`` -- a character with a high error rate
      (``weak_points.character_error_rates``).
    - ``"confusion"`` -- a frequent (intended, typed) substitution
      (``weak_points.confusion_pairs``).
    - ``"bigram"`` -- a slow key-to-key transition
      (``speed.bigram_latencies``, only present once keystrokes have been
      recorded -- absent entirely for older history, in which case this
      degrades to char/confusion targets only).

    Each entry is a dict: ``{"kind", "target", "score", "reason"}`` plus a
    ``"detail"`` dict carrying the raw numbers it was built from. ``target``
    is always a plain string so the whole thing stays JSON-safe: the
    character itself for "char", ``"intended>typed"`` for "confusion", and
    the two-character transition (e.g. ``"th"``) for "bigram".

    **How the three kinds are made comparable (the judgement call):** their
    native metrics are on three different, incommensurable scales -- an
    error rate in [0, 1], a raw occurrence count, and a mean latency in
    milliseconds -- so there is no honest single formula that converts, say,
    "480ms" into the same units as "14 times in 200 attempts". Instead, each
    kind is first ranked *within itself* by its own natural metric (error
    rate for chars, count for confusions, mean_ms for bigrams), and each
    entry's score is its **percentile rank within its own kind's list**:
    1.0 for the worst offender of that kind, sliding down towards (but never
    reaching) 0.0 for the mildest one that still qualified. The three
    percentile-scored lists are then merged and sorted together. This
    treats "the worst character you have" and "the worst bigram you have"
    as equally worth practising regardless of kind, which is a real
    trade-off (a mild bigram problem can outrank a severe character problem
    if the user simply has more bigram data) but is the only comparison that
    does not require an arbitrary cross-kind weighting constant.

    Noise floors, so a single unlucky attempt does not top the list:
    characters need at least ``_MIN_CHAR_SAMPLES`` sightings, confusion
    pairs need at least ``_MIN_CONFUSION_COUNT`` occurrences. Bigrams are
    already floored by ``analysis.bigram_latencies``'s own
    ``min_occurrences``. Whitespace is excluded from "char" targets -- a
    high "error rate" on the space character is usually a length-mismatch
    alignment artefact (see analysis.py's module docstring), not a key the
    user needs to practise.
    """
    weak_points = report.get("weak_points", {})
    speed = report.get("speed", {})

    char_rows = [
        r
        for r in weak_points.get("character_error_rates", {}).get("characters", [])
        if r.get("seen", 0) >= _MIN_CHAR_SAMPLES
        and r.get("mistyped", 0) > 0
        and r.get("char") not in (" ", "\t", "\n")
    ]
    char_rows.sort(key=lambda r: (-r["error_rate"], -r["seen"], r["char"]))

    confusion_rows = [
        r
        for r in weak_points.get("confusion_pairs", {}).get("pairs", [])
        if r.get("count", 0) >= _MIN_CONFUSION_COUNT
    ]
    confusion_rows.sort(key=lambda r: (-r["count"], r["intended"], r["typed"]))

    bigram_rows = list(speed.get("bigram_latencies", {}).get("bigrams", []))
    bigram_rows.sort(key=lambda r: (-(r.get("mean_ms") or 0), r["prev"], r["char"]))
    bigram_median = (
        statistics.median(r["mean_ms"] for r in bigram_rows) if bigram_rows else None
    )

    targets = []

    n = len(char_rows)
    for i, r in enumerate(char_rows):
        score = _percentile_score(i, n)
        reason = (
            f"mistyped {r['mistyped']} times in {r['seen']} attempts "
            f"({r['error_rate'] * 100:.0f}% error rate)"
        )
        targets.append(
            {"kind": "char", "target": r["char"], "score": score, "reason": reason, "detail": r}
        )

    n = len(confusion_rows)
    for i, r in enumerate(confusion_rows):
        score = _percentile_score(i, n)
        reason = f"typed '{r['typed']}' instead of '{r['intended']}', {r['count']} times"
        targets.append(
            {
                "kind": "confusion",
                "target": f"{r['intended']}>{r['typed']}",
                "score": score,
                "reason": reason,
                "detail": r,
            }
        )

    n = len(bigram_rows)
    for i, r in enumerate(bigram_rows):
        score = _percentile_score(i, n)
        if bigram_median:
            ratio = r["mean_ms"] / bigram_median
            reason = (
                f"averages {r['mean_ms']:.0f} ms, {ratio:.1f}x your median transition "
                f"speed of {bigram_median:.0f} ms"
            )
        else:
            reason = f"averages {r['mean_ms']:.0f} ms"
        targets.append(
            {
                "kind": "bigram",
                "target": f"{r['prev']}{r['char']}",
                "score": score,
                "reason": reason,
                "detail": r,
            }
        )

    targets.sort(key=lambda t: -t["score"])
    return targets[:limit]


def _percentile_score(index: int, n: int) -> float:
    """1.0 for the top-ranked item of a list of length ``n``, sliding to 0.

    ``index`` is the item's 0-based position in a list already sorted
    worst/most-severe first. A list of length 1 scores its only item 1.0 --
    there is nothing to compare it to, so it is treated as fully weak within
    its own (tiny) population, which is consistent with how every other
    single-item list here would be read.
    """
    if n <= 0:
        return 0.0
    return round((n - index) / n, 4)


# ---------------------------------------------------------------------------
# 2. generate_drill
# ---------------------------------------------------------------------------


def _words_containing_char(ch: str) -> list:
    if not ch or len(ch) != 1 or not ch.isalpha():
        return []
    ch = ch.lower()
    return [w for w in _WORD_BANK if ch in w]


def _words_containing_bigram(bg: str) -> list:
    if not bg or len(bg) != 2 or not bg.isalpha():
        return []
    bg = bg.lower()
    return [w for w in _WORD_BANK if bg in w]


def _synthesize_word(rng: random.Random, ch: str | None) -> str:
    """A short, typeable pseudo-word for a character the word bank has no word for.

    Used for characters the ``_WORD_BANK`` cannot supply a real word for --
    digits, punctuation, or (in principle) a non-ASCII letter. Wraps the
    character in ordinary lowercase vowels so the result is still something
    an ordinary keyboard can type and a person can read as "a word", even
    though it is not a real one; see the module-level note that these are
    synthetic drills, not prose.

    A whitespace ``ch`` (e.g. the space half of a "word boundary" bigram
    like ``" a"``) cannot be wrapped this way -- embedding a space *inside*
    what is meant to be a single pool entry would silently produce a
    double space once entries are joined with ``" ".join``. There is
    nothing sensible to drill for "the gap between words" on its own, so
    that case falls back to a plain word from the bank instead.
    """
    fillers = ("a", "i", "o")
    if not ch or ch.isspace():
        return rng.choice(_WORD_BANK)
    lead, tail = rng.choice(fillers), rng.choice(fillers)
    return f"{lead}{ch}{tail}{ch}"


def generate_drill(targets: list, length: int = 60, seed: int | None = None) -> str:
    """Synthesise a practice line built around ``targets``.

    **This is synthetic practice text, not prose** -- ordinary lowercase
    words drawn from a small built-in word bank (or, when no bank word
    contains the needed character, a short constructed pseudo-word) chosen
    because they contain the weak characters, confusion letters or slow
    bigrams from ``weak_targets``, repeated with variation until the line is
    about ``length`` characters. It is meant to be typed, not read for
    meaning.

    Deterministic when ``seed`` is given: uses ``random.Random(seed)``
    locally, never the global ``random`` module, so the same targets and
    seed always produce the same line and calling this does not perturb
    randomness anywhere else in the process. ``seed=None`` (the default)
    uses OS randomness and is not reproducible.

    Only ordinary lowercase letters and single spaces appear in the output
    (the word bank and the pseudo-word fallback are both built that way),
    so the result only ever contains characters an ordinary keyboard can
    type -- no control characters, no line noise.

    Returns ``""`` for an empty ``targets`` list.
    """
    rng = random.Random(seed)
    if not targets:
        return ""

    per_target_words: list = []
    pool: list = []
    for t in targets:
        kind = t.get("kind")
        target = t.get("target") or ""
        words: list = []
        fallback_char = None
        if kind == "char":
            words = _words_containing_char(target)
            fallback_char = target
        elif kind == "confusion":
            intended, _, typed = str(target).partition(">")
            words = _words_containing_char(intended) or _words_containing_char(typed)
            fallback_char = intended or typed
        elif kind == "bigram":
            words = _words_containing_bigram(target)
            fallback_char = target[0] if target else None
        if not words:
            words = [_synthesize_word(rng, fallback_char)]
        per_target_words.append(words)
        pool.extend(words)

    if not pool:
        return ""
    pool = list(dict.fromkeys(pool))  # dedupe, preserve deterministic order

    # Seed the line with one word per target first, so every weak point the
    # caller asked for is guaranteed to appear at least once -- a purely
    # random draw from the merged pool could easily skip a target with few
    # matching words in favour of one with many. Remaining length is then
    # filled by random draws from the whole pool for variety and repetition.
    line_words: list = [rng.choice(words) for words in per_target_words]
    rng.shuffle(line_words)
    total_len = sum(len(w) for w in line_words) + max(0, len(line_words) - 1)

    while total_len < length:
        word = rng.choice(pool)
        added = len(word) + (1 if line_words else 0)
        if line_words and total_len + added > length:
            break
        line_words.append(word)
        total_len += added

    if not line_words:
        line_words = [pool[0]]
    return " ".join(line_words)


# ---------------------------------------------------------------------------
# 3. find_hard_line
# ---------------------------------------------------------------------------


def _count_target_occurrences(kind: str, target: str, line: str) -> int:
    if kind == "char":
        return line.count(target)
    if kind == "confusion":
        intended = str(target).partition(">")[0]
        return line.count(intended) if intended else 0
    if kind == "bigram":
        if len(target) != 2:
            return 0
        return sum(1 for i in range(len(line) - 1) if line[i : i + 2] == target)
    return 0


def find_hard_line(lines: list, targets: list, start: int = 0, limit: int = 5) -> list:
    """The upcoming lines of the book densest in the user's weak targets.

    "Find me a hard line" (docs/UI_Refresh_Notes.md, Proposal C): practising
    weaknesses against the actual book the user is reading is the better
    exercise over a synthetic drill whenever a suitably dense line exists,
    because it is also forward progress through the text.

    ``lines`` is the whole book (``Text.contents``); only indices from
    ``start`` onward are considered, so a line already typed is never
    suggested. Each candidate line's score is
    ``sum(count(target) * target["score"]) / len(line)`` -- occurrences of
    each target, weighted by how severe ``weak_targets`` judged that target,
    normalised by line length so a long line is not favoured purely for
    having more characters to match against. Lines with no matches at all
    are dropped rather than scored zero.

    Returns up to ``limit`` entries, each
    ``{"line_index", "line", "score", "targets_matched"}``, sorted by score
    descending (ties broken by earliest line, so progress is not skipped
    over arbitrarily).
    """
    candidates = []
    for idx in range(max(start, 0), len(lines)):
        line = lines[idx]
        if not line:
            continue
        matched = []
        weighted_score = 0.0
        for t in targets:
            count = _count_target_occurrences(t.get("kind"), t.get("target"), line)
            if count:
                matched.append({"kind": t.get("kind"), "target": t.get("target"), "count": count})
                weighted_score += count * t.get("score", 1.0)
        if matched:
            candidates.append(
                {
                    "line_index": idx,
                    "line": line,
                    "score": _round(weighted_score / len(line)),
                    "targets_matched": matched,
                }
            )
    candidates.sort(key=lambda c: (-c["score"], c["line_index"]))
    return candidates[:limit]


# ---------------------------------------------------------------------------
# 4. trouble_words
# ---------------------------------------------------------------------------


def trouble_words(report: dict, limit: int = 20) -> list:
    """The watchlist: real book words most often mistyped, and how.

    A thin reshaping of ``weak_points.problem_words`` (already ranked by
    ``Counter.most_common``, so this only truncates and renames the field).
    ``common_wrong_version`` is really "the first wrong version seen", not
    "the most common one" -- ``analysis.problem_words`` only keeps one
    example per word (``examples.setdefault``), so if a word is mistyped
    several different ways this shows whichever wrong version happened
    first, not the most frequent one.
    """
    words = report.get("weak_points", {}).get("problem_words", {}).get("words", [])
    return [
        {
            "word": w["word"],
            "count": w["count"],
            "common_wrong_version": w.get("example_typed", ""),
        }
        for w in words[:limit]
    ]


# ---------------------------------------------------------------------------
# 5. suggest_criteria
# ---------------------------------------------------------------------------

#: The largest single step this will ever propose for the WPM floor, so a
#: single very fast session cannot suddenly demand a huge jump.
_WPM_STEP_CAP = 10.0
#: How far of the way from the current floor towards the recent rolling
#: average a single suggestion moves -- "a modest step up", not "match your
#: best".
_WPM_STEP_FRACTION = 0.5
#: Only propose raising the WPM floor once the rolling average clears it by
#: more than this margin, so noise around the current floor is not treated
#: as room to raise it.
_WPM_MARGIN = 1.1

_ACCURACY_STEP_CAP = 0.02
_ACCURACY_MARGIN = 0.02


def suggest_criteria(report: dict, settings) -> dict:
    """Propose a modestly higher pass bar from recent rolling performance.

    Reads the most recent point of ``progress.learning_curve`` (already a
    rolling mean over ``analysis.learning_curve``'s ``window``, default the
    last 10 attempts) and compares it to the *current* ``min_wpm`` /
    ``min_accuracy`` on ``settings`` (a ``config.Settings`` or an equivalent
    dict). ``settings`` is read, never written -- this function only
    advises; applying the suggestion is the caller's decision entirely.

    **This never proposes a criterion lower than the current one.** A pass
    bar is a commitment the user set for themselves; a bad day pulling the
    rolling average below it is exactly the situation the bar exists to
    catch; quietly relaxing it in response would make the criteria track
    the user's current performance instead of pushing it, which defeats the
    point of having a floor at all. If recent performance has not cleared
    the current bar by a comfortable margin, the proposal is simply "no
    change" -- never a decrease.

    Returns ``{"current_min_wpm", "current_min_accuracy", "proposed_min_wpm",
    "proposed_min_accuracy", "reasoning"}``. With no scored attempts yet,
    the proposal equals the current settings and the reasoning says so.
    """
    current_min_wpm = float(_get(settings, "min_wpm", 20.0))
    current_min_accuracy = float(_get(settings, "min_accuracy", 1.0))

    points = report.get("progress", {}).get("learning_curve", {}).get("points", [])
    if not points:
        return {
            "current_min_wpm": current_min_wpm,
            "current_min_accuracy": current_min_accuracy,
            "proposed_min_wpm": current_min_wpm,
            "proposed_min_accuracy": current_min_accuracy,
            "reasoning": "not enough scored attempts yet to suggest new criteria.",
        }

    last = points[-1]
    rolling_wpm = last.get("rolling_mean_wpm")
    rolling_accuracy = last.get("rolling_mean_accuracy")

    proposed_wpm = current_min_wpm
    wpm_reason = None
    if rolling_wpm is not None and rolling_wpm > current_min_wpm * _WPM_MARGIN:
        step = min(_WPM_STEP_CAP, (rolling_wpm - current_min_wpm) * _WPM_STEP_FRACTION)
        proposed_wpm = round(current_min_wpm + step, 1)
        wpm_reason = (
            f"your recent rolling average is {rolling_wpm:.1f} wpm, above the current "
            f"{current_min_wpm:.0f} wpm minimum, so raising it to {proposed_wpm:.0f} wpm "
            "is a modest step up"
        )

    proposed_accuracy = current_min_accuracy
    acc_reason = None
    if (
        rolling_accuracy is not None
        and current_min_accuracy < 1.0
        and rolling_accuracy > current_min_accuracy + _ACCURACY_MARGIN
    ):
        step = min(_ACCURACY_STEP_CAP, rolling_accuracy - current_min_accuracy)
        proposed_accuracy = round(min(1.0, current_min_accuracy + step), 4)
        acc_reason = (
            f"your recent rolling accuracy is {rolling_accuracy * 100:.1f}%, above the "
            f"current {current_min_accuracy * 100:.0f}% minimum, so raising it to "
            f"{proposed_accuracy * 100:.0f}% is a modest step up"
        )

    if wpm_reason is None and acc_reason is None:
        reasoning = "recent performance is close to the current criteria -- no change suggested."
    else:
        reasoning = " ".join(r for r in (wpm_reason, acc_reason) if r)

    return {
        "current_min_wpm": current_min_wpm,
        "current_min_accuracy": current_min_accuracy,
        "proposed_min_wpm": proposed_wpm,
        "proposed_min_accuracy": proposed_accuracy,
        "reasoning": reasoning,
    }


# ---------------------------------------------------------------------------
# 6. practice_plan -- the entry point
# ---------------------------------------------------------------------------


def _load_text_lines(text_name: str) -> list:
    """The book's lines for ``text_name``, or ``[]`` if it cannot be loaded.

    Uses ``session.available_texts()`` so this agrees with whatever the game
    itself would load (bundled vs. user library, name collisions and all),
    rather than re-deriving that lookup. Failures (missing file, text not
    found) degrade to an empty list rather than raising: a hard line is a
    bonus in the practice plan, not something its absence should break.
    """
    try:
        library = session.available_texts()
        if text_name not in library:
            return []
        folder, filename, _source = library[text_name]
        text = texts.Text(text_name, filename)
        text.load(folder)
        return list(text.contents or [])
    except OSError:
        return []


def practice_plan(text_name: str | None = None) -> dict:
    """Read the store and assemble one practice plan. The only store-touching function here.

    Combines ``weak_targets``, one ``generate_drill`` line, ``find_hard_line``
    over ``text_name``'s book (when one is given and loadable), the
    ``trouble_words`` watchlist, and a ``suggest_criteria`` proposal into a
    single JSON-serialisable dict.

    A brand-new user (no scored attempts at all for ``text_name``) gets
    ``has_enough_data: False`` and a plain "not enough data yet, keep
    typing" message instead of an exception or a divide-by-zero -- every
    analysis function under it already tolerates empty input, but this is
    the one place that says so in a way a UI can show directly.
    """
    report = analysis.full_report(text_name=text_name)
    settings = config.load()
    total_attempts = report.get("data_coverage", {}).get("total_attempts", 0)

    if not total_attempts:
        return {
            "text_name": text_name,
            "has_enough_data": False,
            "message": "not enough data yet, keep typing",
            "targets": [],
            "drill": "",
            "hard_lines": [],
            "trouble_words": [],
            "criteria_suggestion": suggest_criteria(report, settings),
        }

    targets = weak_targets(report)
    drill = generate_drill(targets) if targets else ""

    hard_lines: list = []
    if text_name and targets:
        lines = _load_text_lines(text_name)
        if lines:
            start = history.get_position(text_name, 0)
            hard_lines = find_hard_line(lines, targets, start=start)

    return {
        "text_name": text_name,
        "has_enough_data": True,
        "message": None,
        "targets": targets,
        "drill": drill,
        "hard_lines": hard_lines,
        "trouble_words": trouble_words(report),
        "criteria_suggestion": suggest_criteria(report, settings),
    }
