import tkinter as tk
from TypingTrainer import Game
from functions import setup_window

DEBUG = True

root = tk.Tk()
width = 1200
height = 700
canvas = setup_window(root, screen_dims=(1920, 1080), window_dims=(width, height), scaling=1.25)
canvas.grid(columnspan=3, rowspan=4)

type_trainer = Game(root)

root.mainloop()
