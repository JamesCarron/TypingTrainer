"""Window geometry for the tkinter front end.

``setup_window`` moved here verbatim from the old flat ``functions.py`` during the
stage 3 engine extraction (see docs/Refactor_Plan.md), because it is the one
tkinter-only function that lived among the pure ones.
"""

import tkinter as tk


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
