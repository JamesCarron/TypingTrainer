from itertools import zip_longest
from tkinter.filedialog import askopenfile
from os import getcwd
import tkinter as tk
import re


#################################
# --------- FUNCTIONS --------- #
#################################

def setup_window(root, screen_dims, window_dims, scaling=1.25):
    screen_w = int(screen_dims[0] / scaling)
    screen_h = int(screen_dims[1] / scaling)

    width = window_dims[0]
    height = window_dims[1]

    scaling_fix = 0.5
    border_w = int((screen_w - width) / 2)
    border_h = int(((screen_h - height) / 2) * scaling_fix)

    root.geometry('+%d+%d' % (border_w, border_h))

    return tk.Canvas(root, width=width, height=height)


def compare_lines(guess, answer):
    """
    Char by char comparison. True when chars are the same False otherwise.
    output is filled with False values up to the length of the longest input
    :param guess: the guess
    :param answer: the correct answer
    :return:
    """
    return [g == a for (g, a) in zip_longest(guess, answer, fillvalue=False)]


def typing_score(guess, answer, total_time):
    # Compare user input to given sentence character by character
    matches = compare_lines(guess, answer)
    accuracy = round(sum(matches) / len(answer), 4)  # 100.00% aka 1.0000
    wpm = round(sum(matches) * 60 / (5 * total_time), 2)  # Calculate words per minute
    results = {'matches': matches,
               'accuracy': accuracy,
               'wpm': wpm,
               'duration': total_time}
    return results


def str_find_all(a_str, sub):
    start = 0
    while True:
        start = a_str.find(sub, start)
        if start == -1: return
        yield start
        start += len(sub)  # use start += 1 to find overlapping matches


def subdivide_line(line, line_len_limit=100, split_type='LHS'):
    min_line_length = 10
    """
    Takes a string and tries to divide it into strings at punctuation points
    so each string is shorter then line_len_limit characters.
    Tries to divide as close to the centre of the string as possible
    Returns a list of strings which satisfy this criteria.
    Recursive function
    """

    punctuation = ['.', '?', '!']

    # if line is already short enough or there is no place we can split. Return the line
    if len(line) <= line_len_limit or sum(punc in line[min_line_length:line_len_limit] for punc in punctuation) == 0:
        return [line]

    line_centre = int(len(line) / 2)  # 20->10, 21->10, 19->9
    punc_pos = dict()

    if split_type.upper() == 'CENTRE':
        # TODO: This can be written better
        for punc in punctuation:  # find all the possible places we can split at
            punc_pos.update({i: abs(i - line_centre) for i in str_find_all(line, punc)})
        split_pos = int([i for i in punc_pos if punc_pos[i] == min(punc_pos.values())][0])

    # make lines closest to char limit.
    elif split_type.upper() == 'LHS':
        possible_split_pos = list()
        for punc in punctuation:
            possible_split_pos += [i for i in str_find_all(line, punc) if i < line_len_limit]
        if len(possible_split_pos) > 0:  # no punctuation found before line_len_limit
            split_pos = max(possible_split_pos)
        else:
            for punc in punctuation:
                possible_split_pos += [i for i in str_find_all(line, punc) if i >= line_len_limit]
            if len(possible_split_pos) == 0:  # no punctuation found after line_len_limit either. exit
                return [line]
            split_pos = min(possible_split_pos)

    else:
        raise ValueError(f'subdivide_line(): split_type argument is invalid, Value Passed: {split_type}')

    for punc in punctuation:  # check which punctuation mark is here:
        if line[split_pos:split_pos + len(punc)] == punc:
            split_line = [line[:split_pos + len(punc)], line[split_pos + len(punc):]]
            break
    else:  # if no punctuation marks are found, this should never occur
        split_line = line

    # TODO: revisit, this is hard to change into a list comprehension due to the needed unpacking
    shortened_lines = list()
    for line_sub in split_line:
        shortened_lines += subdivide_line(line_sub.strip(), line_len_limit)
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
    def subdivide_centre():
        string_a70_qm_a20_qm_a40 = ''.join(['a' * 70, '?', 'a' * 20, '?', 'a' * 40])
        # print(string_a70_qm_a20_qm_a40)

        # centre should split at first qm,
        string_a70_qm = ''.join(['a' * 70, '?'])
        string_a20_qm_a40 = ''.join(['a' * 20, '?', 'a' * 40])
        subdiv_str = subdivide_line(string_a70_qm_a20_qm_a40, line_len_limit=100, split_type='CENTRE')

        assert subdiv_str == [string_a70_qm, string_a20_qm_a40]
        print("PASS: subdivide_line(), split_type='CENTRE' condition")

    def subdivide_lhs():
        string_a70_qm_a20_qm_a40 = ''.join(['a' * 70, '?', 'a' * 20, '?', 'a' * 40])
        # print(string_a70_qm_a20_qm_a40)

        # LHS should split at second qm
        string_a70_qm_a20_qm = ''.join(['a' * 70, '?', 'a' * 20, '?'])
        string_a40 = ''.join(['a' * 40])
        subdiv_str = subdivide_line(string_a70_qm_a20_qm_a40, line_len_limit=100, split_type='LHS')

        assert subdiv_str == [string_a70_qm_a20_qm, string_a40]
        print("PASS: subdivide_line(), split_type='LHS' condition")

    tests = [subdivide_centre, subdivide_lhs]
    for test in tests:
        try:
            test()
        except AssertionError:
            print(f"Failed test")


if __name__ == '__main__':
    run_tests()
