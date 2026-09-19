"""Pure text-wrapping logic for TypingTrainer: splitting long lines at punctuation.

Extracted verbatim (same behaviour, same edge cases) from the pre-refactor
`functions.py` (str_find_all, subdivide_line). No UI, no I/O.

Written 2026-09-19 for the "Golden tests" stream of Wave A of the TypingTrainer
refactor (see docs/Refactor_Plan.md). Verified by tests/test_linebreak.py.
"""


def str_find_all(a_str, sub):
    """Find all occurrences of a substring in a string.

    Generator function that yields the starting index of each occurrence
    of the substring in the string.

    Args:
        a_str: The string to search in
        sub: The substring to search for

    Yields:
        int: Starting index of each occurrence of sub in a_str
    """
    start_index = 0
    while True:
        match_index = a_str.find(sub, start_index)
        if match_index == -1:
            return
        yield match_index
        start_index = match_index + len(
            sub
        )  # use start += 1 to find overlapping matches


def subdivide_line(line, line_len_limit=100, split_type="LHS"):
    """Divide a long string into shorter strings at punctuation points.

    Recursively splits a string at punctuation marks (. ? !) to create
    segments shorter than line_len_limit. Splitting strategy depends on
    split_type parameter.

    Args:
        line: The string to subdivide
        line_len_limit: Maximum length for each segment in characters (default: 100)
        split_type: Splitting strategy - 'LHS' splits near the limit, 'CENTRE' splits near center (default: 'LHS')

    Returns:
        list[str]: List of subdivided strings, each <= line_len_limit characters

    Raises:
        ValueError: If split_type is not 'LHS' or 'CENTRE'
    """
    min_split_index = 10
    punctuation = [".", "?", "!"]
    split_type_upper = split_type.upper()

    # if line is already short enough or there is no place we can split. Return the line
    if len(line) <= line_len_limit or not any(
        punc in line[min_split_index:line_len_limit] for punc in punctuation
    ):
        return [line]

    line_center_index = int(len(line) / 2)  # 20->10, 21->10, 19->9

    if split_type_upper == "CENTRE":
        punctuation_distance_map = {}
        for punc in punctuation:  # find all the possible places we can split at
            for index in str_find_all(line, punc):
                punctuation_distance_map[index] = abs(index - line_center_index)
        split_pos = min(punctuation_distance_map, key=punctuation_distance_map.get)

    # make lines closest to char limit.
    elif split_type_upper == "LHS":
        candidates_before_limit = []
        for punc in punctuation:
            candidates_before_limit.extend(
                [index for index in str_find_all(line, punc) if index < line_len_limit]
            )
        if candidates_before_limit:  # no punctuation found before line_len_limit
            split_pos = max(candidates_before_limit)
        else:
            candidates_after_limit = []
            for punc in punctuation:
                candidates_after_limit.extend(
                    [
                        index
                        for index in str_find_all(line, punc)
                        if index >= line_len_limit
                    ]
                )
            if (
                not candidates_after_limit
            ):  # no punctuation found after line_len_limit either. exit
                return [line]
            split_pos = min(candidates_after_limit)

    else:
        raise ValueError(
            f"subdivide_line(): split_type argument is invalid, Value Passed: {split_type}"
        )

    split_line = line
    for punc in punctuation:  # check which punctuation mark is here:
        if line[split_pos : split_pos + len(punc)] == punc:
            split_line = [
                line[: split_pos + len(punc)],
                line[split_pos + len(punc) :],
            ]
            break

    shortened_lines = []
    for line_sub in split_line:
        shortened_lines.extend(subdivide_line(line_sub.strip(), line_len_limit))
    return shortened_lines
