"""Pure scoring logic for TypingTrainer: character comparison, accuracy/WPM, pass/fail.

Extracted verbatim (same behaviour, same rounding, same edge cases) from the
pre-refactor `functions.py` (compare_lines, typing_score) and from
`TypingTrainer.py`'s `Game.passing_grade` (passing_grade). No UI, no clock: every
function here is a pure function of its arguments.

Written 2026-09-19 for the "Golden tests" stream of Wave A of the TypingTrainer
refactor (see docs/Refactor_Plan.md). Verified by tests/test_scoring.py.
"""

import itertools


def compare_lines(guess, answer):
    """Compare two strings character by character.

    Performs character-by-character comparison between guess and answer strings.
    Output is filled with False values up to the length of the longest input.

    Args:
        guess: The user's input string
        answer: The correct answer string

    Returns:
        list[bool]: List of boolean values, True where characters match, False otherwise
    """
    return [
        guess_char == answer_char
        for (guess_char, answer_char) in itertools.zip_longest(
            guess, answer, fillvalue=False
        )
    ]


def typing_score(guess, answer, total_time):
    """Calculate typing statistics including accuracy and words per minute.

    Compares user input to the target text and calculates:
    - Character-by-character matches
    - Accuracy as percentage of correct characters
    - Words per minute (WPM) based on correct characters

    Args:
        guess: The user's typed input
        answer: The target text to match
        total_time: Time taken in seconds

    Returns:
        dict: Dictionary containing 'matches' (list), 'accuracy' (float), 'wpm' (float), and 'duration' (float)
    """
    # Compare user input to given sentence character by character
    matches = compare_lines(guess, answer)
    correct_chars = sum(matches)
    # An empty target line used to raise ZeroDivisionError here. Fixed
    # 2026-09-19: an empty guess against an empty target is perfect, anything
    # typed against an empty target is not. Reachable only through a corpus
    # with a blank line, but it crashed the attempt when it happened.
    if not answer:
        accuracy = 1.0 if not guess else 0.0
    else:
        accuracy = round(correct_chars / len(answer), 4)  # 100.00% aka 1.0000
    # Guarded for the same reason: a zero duration is not a human typing.
    wpm = (
        round(correct_chars * 60 / (5 * total_time), 2) if total_time else 0.0
    )  # Calculate words per minute
    return {
        "matches": matches,
        "accuracy": accuracy,
        "wpm": wpm,
        "duration": total_time,
    }


def passing_grade(results, *, require_accuracy, min_accuracy, require_wpm, min_wpm):
    """Determine whether a typing attempt meets the active pass criteria.

    Lifted from Game.passing_grade in the pre-refactor TypingTrainer.py, with
    the per-instance settings passed in instead of read off ``self``.

    One deliberate change from the original, made 2026-09-19: the
    "accuracy above 100%" sanity check used to sit *inside* the
    ``require_accuracy`` branch, so an impossible score sailed through
    whenever that criterion happened to be switched off. It is a check on the
    scorer, not on the criterion, so it now runs either way.

    Args:
        results: Dictionary containing 'accuracy' and 'wpm' keys
        require_accuracy: whether accuracy is a pass/fail criterion
        min_accuracy: minimum accuracy (0-1) required to pass, when require_accuracy is set
        require_wpm: whether WPM is a pass/fail criterion
        min_wpm: minimum WPM required to pass, when require_wpm is set

    Returns:
        bool: True if every active criterion is met, False otherwise

    Raises:
        ValueError: if accuracy exceeds 100%, which means the scorer is wrong
    """
    if results["accuracy"] > 1:
        raise ValueError(f"results['accuracy'] > 100% - {results['accuracy']:=}")

    if require_accuracy and results["accuracy"] < min_accuracy:
        return False

    if require_wpm and results["wpm"] < min_wpm:
        return False

    return True
