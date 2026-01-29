import tkinter as tk

from TypingTrainer import Game
from functions import setup_window

DEBUG = True

root = tk.Tk()
width = 1200
height = 500
canvas = setup_window(
    root, screen_dims=(1920, 720), window_dims=(width, height), scaling=1.0
)
canvas.grid(columnspan=3, rowspan=3)

type_trainer = Game(root)

root.mainloop()
