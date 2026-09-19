"""Thin shim re-exporting scoring/linebreak logic from the typingtrainer package.

Pre-refactor, this module held setup_window (tkinter), compare_lines, typing_score,
str_find_all, subdivide_line, and a run_tests() self-check. As of the "Golden tests"
stream of Wave A (see docs/Refactor_Plan.md), the pure logic lives in
src/typingtrainer/scoring.py and src/typingtrainer/linebreak.py, covered by
tests/test_scoring.py and tests/test_linebreak.py; run_tests() and its inner helpers
are deleted, their cases absorbed into that suite. setup_window stays here -- it is
tkinter code that a later stage moves into desktop/window.py -- so TypingTrainer.py /
main.py keep importing everything from here unchanged.
"""

import tkinter as tk

from typingtrainer.linebreak import str_find_all, subdivide_line
from typingtrainer.scoring import compare_lines, typing_score

__all__ = [
    "setup_window",
    "compare_lines",
    "typing_score",
    "str_find_all",
    "subdivide_line",
]


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
