import itertools
from tkinter.filedialog import askopenfile
from os import getcwd
import tkinter as tk
import re


#################################
# --------- FUNCTIONS --------- #
#################################


def setup_window(root, screen_dims, window_dims, scaling=1.25):
    """Setup and center the application window on the screen.

    Args:
        root: tkinter root window
        screen_dims: Tuple of (width, height) for screen dimensions in pixels
        window_dims: Tuple of (width, height) for window dimensions in pixels
        scaling: Display scaling factor (default: 1.25)

    Returns:
        tk.Canvas: Canvas widget with specified dimensions
    """
    scaled_screen_width = int(screen_dims[0] / scaling)
    scaled_screen_height = int(screen_dims[1] / scaling)

    window_width = window_dims[0]
    window_height = window_dims[1]

    vertical_scaling_fix = 0.5
    x_offset = int((scaled_screen_width - window_width) / 2)
    y_offset = int(((scaled_screen_height - window_height) / 2) * vertical_scaling_fix)

    root.geometry("+%d+%d" % (x_offset, y_offset))

    return tk.Canvas(root, width=window_width, height=window_height)


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
    accuracy = round(correct_chars / len(answer), 4)  # 100.00% aka 1.0000
    wpm = round(correct_chars * 60 / (5 * total_time), 2)  # Calculate words per minute
    return {
        "matches": matches,
        "accuracy": accuracy,
        "wpm": wpm,
        "duration": total_time,
    }


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


# def add_textfile():
#     global root
#     """
#     Allows the user to add a text to the trainer.
#     :return:
#     """
#     browse_text.set('Loading...')
#     file = askopenfile(parent=root, initialdir=getcwd(), title="Choose a file", filetype=[("Text file", '*.txt')])
#     if file != None:
#         print("File was loaded successfully")
#         text = [line.strip() for line in file.readlines()]
#
#         # text box
#         text_box = tk.Text(root, height=10, width=50, padx=15, pady=15)
#         text_box.insert(1.0, f"{nl.join(text)}")
#         text_box.tag_configure('center', justify='center')
#         text_box.tag_add('center', 1.0, 'end')
#         text_box.grid(column=1, row=3)
#         browse_text.set('Loaded')
#     else:
#         print("Something went wrong")
#         browse_text.set('Browse')


def run_tests():
    """Run test suite for the subdivide_line function.

    Tests both 'CENTRE' and 'LHS' split types with predefined test cases.
    Prints PASS messages for successful tests or failure messages for failed assertions.
    """

    def subdivide_centre():
        long_string = "".join(["a" * 70, "?", "a" * 20, "?", "a" * 40])
        # print(string_a70_qm_a20_qm_a40)

        # centre should split at first qm,
        string_a70_qm = "".join(["a" * 70, "?"])
        string_a20_qm_a40 = "".join(["a" * 20, "?", "a" * 40])
        subdiv_str = subdivide_line(
            long_string, line_len_limit=100, split_type="CENTRE"
        )

        assert subdiv_str == [string_a70_qm, string_a20_qm_a40]
        print("PASS: subdivide_line(), split_type='CENTRE' condition")

    def subdivide_lhs():
        string_a70_qm_a20_qm_a40 = "".join(["a" * 70, "?", "a" * 20, "?", "a" * 40])
        # print(string_a70_qm_a20_qm_a40)

        # LHS should split at second qm
        string_a70_qm_a20_qm = "".join(["a" * 70, "?", "a" * 20, "?"])
        string_a40 = "".join(["a" * 40])
        string_a70_qm_a20_qm_a40 = "".join([string_a70_qm_a20_qm, string_a40])

        subdiv_str = subdivide_line(
            string_a70_qm_a20_qm_a40, line_len_limit=100, split_type="LHS"
        )

        assert subdiv_str == [string_a70_qm_a20_qm, string_a40]
        print("PASS: subdivide_line(), split_type='LHS' condition")

    tests = [subdivide_centre, subdivide_lhs]
    for test in tests:
        try:
            test()
        except AssertionError:
            print("Failed test")


if __name__ == "__main__":
    run_tests()
