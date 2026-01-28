import tkinter as tk
from PIL import Image, ImageTk
from os import path
from os import getcwd
from datetime import datetime
import pickle  # for loading and saving game info
from sys import exit
from Texts import Text
from functions import *


class Game:

    def __init__(self, root, window_width=1200, window_height=700):
        self.DEBUG = False
        self.root_dir = getcwd()
        self.texts_dir = path.join(self.root_dir, "Texts")
        self.root = root
        self.root.title("TypingTrainer")
        self.root.tk.call(
            "wm", "iconphoto", root._w, tk.PhotoImage(file="Images/ico.png")
        )
        self.width = window_width
        self.height = window_height
        self.display_nlines = 5

        self.state = str()
        self.user_input = ""
        self.user_input_full = ""
        self.results_str = ""

        self.available_texts = {"Art of War": "artofwar.txt"}
        chosen_text = "Art of War"
        self.text = Text(chosen_text, self.available_texts[chosen_text])
        self.text.load(self.texts_dir)
        self.game_settings = {
            "Texts": {self.text.name: {"line": self.text.position}}
        }  # initialise the variable
        self.game_settings = dict()
        self.game_history = dict()
        self.save_fname = "SaveGame.pickleddict"
        self.load_game()

        #################################
        # ------------ GUI ------------ #
        #################################
        text_style = ("Raleway", 18)  # font settings for text box
        textname_style = ("Raleway", 30)
        title_style = ("Eras Medium ITC", 60)
        button_style = ("Raleway", 12)

        acc_primary_c = "#20bebe"
        acc_primary_fc = "white"

        # logo image
        logo = ImageTk.PhotoImage(Image.open(r"Images\TyperIcon_30.png"))
        self.logo_label = tk.Label(image=logo)
        self.logo_label.image = logo
        self.logo_label.grid(column=2, row=0)

        # Text name
        self.textname = tk.Label(
            root, text=f'Text Name: \n"{self.text.name}"', font=textname_style
        )
        self.textname.grid(column=0, row=0)

        # Title
        self.title = tk.Label(root, text=f"Typing\nTrainer", font=title_style)
        self.title.grid(column=1, row=0)

        # page input
        self.text_box = tk.Text(
            root,
            height=self.display_nlines,
            width=int(self.width * 0.055),
            padx=5,
            pady=5,
            font=text_style,
        )
        self.text_box.grid(column=0, row=1, columnspan=3)
        self.text_box.config(wrap="word")
        self.draw_textbox()

        # user input
        # self.userinput_box = tk.Text(
        #     root,
        #     height=4,
        #     width=int(self.width * 0.055),
        #     padx=5,
        #     pady=5,
        #     font=text_style,
        # )
        # self.userinput_box.grid(column=0, row=2, columnspan=3)
        # self.userinput_box.config(wrap="word")
        # self.draw_userinput()

        # instructions
        self.instructions = tk.Label(root, text="Press Enter to start", font="Raleway")
        self.instructions.grid(column=1, row=3)

        # prev line button
        browse_text = tk.StringVar()
        brows_btn = tk.Button(
            root,
            textvariable=browse_text,
            command=lambda: self.change_pos(-1),
            font=button_style,
            bg=acc_primary_c,
            fg=acc_primary_fc,
            height=1,
            width=10,
        )
        browse_text.set("Prev")
        brows_btn.grid(column=0, row=3)

        # # save button
        # browse_text = tk.StringVar()
        # brows_btn = tk.Button(root, textvariable=browse_text,
        #                       command=lambda: self.save_game(),
        #                       font=button_style, bg=acc_primary_c, fg=acc_primary_fc, height=1, width=10)
        # browse_text.set("Save Game")
        # brows_btn.grid(column=1, row=4)

        # next line button
        browse_text = tk.StringVar()
        brows_btn = tk.Button(
            root,
            textvariable=browse_text,
            command=lambda: self.change_pos(1),
            font=button_style,
            bg=acc_primary_c,
            fg=acc_primary_fc,
            height=1,
            width=10,
        )
        browse_text.set("Next")
        brows_btn.grid(column=2, row=3)

        # STYLING EXPERIMENTATION
        # import tkinter.font as tkFont
        # self.font_index = 0
        # self.fonts = list(tkFont.families())
        # self.change_font(self.title, 0, 60)  # set to start
        # self.font_shortlist = list()
        # # prev font button
        # browse_text = tk.StringVar()
        # font_btn = tk.Button(root, textvariable=browse_text,
        #                       command=lambda: self.change_font(self.title, -1),
        #                       font=button_style, bg=acc_primary_c, fg=acc_primary_fc, height=1, width=10)
        # browse_text.set("PrevFont")
        # font_btn.grid(column=0, row=5)
        #
        # # font shortlist button
        # browse_text = tk.StringVar()
        # font_btn = tk.Button(root, textvariable=browse_text,
        #                       command=lambda: self.shortlist_font(),
        #                       font=button_style, bg=acc_primary_c, fg=acc_primary_fc, height=1, width=10)
        # browse_text.set("AddFontToShortlist")
        # font_btn.grid(column=1, row=5)
        #
        # # next font button
        # browse_text = tk.StringVar()
        # font_btn = tk.Button(root, textvariable=browse_text,
        #                       command=lambda: self.change_font(self.title, 1, 60),
        #                       font=button_style, bg=acc_primary_c, fg=acc_primary_fc, height=1, width=10)
        # browse_text.set("NextFont")
        # font_btn.grid(column=2, row=5)

        #################################
        # ---------- STARTUP ---------- #
        #################################

        root.bind("<Key>", self.key_handler)
        self.time_start = datetime.now()
        self.set_state("READY")

    def change_font(self, item, n, shortlist=None, size=60):
        self.font_index += n
        try:
            font = self.fonts[self.font_index]
        except IndexError:
            if n > 0:
                self.font_index = 0
                font = self.fonts[self.font_index]
            else:
                self.font_index = len(self.fonts)
                font = self.fonts[self.font_index]

        # shortlist = ["Copperplate Gothic Bold", "Gill Sans MT",  "Georgia", "Sitka Small", "System", "Courier New",
        # "Eras Light ITC", "Papyrus", "Eras Medium ITC", "Copperplate Gothic Light", "HGPKyokashotai", "Roboto Slab",
        # "HGMaruGothicMPRO", "Courier"]

        shortlist = ["Eras Medium ITC"]

        if shortlist is None:
            skip_fonts = ["Cambria Math"]
            while font in skip_fonts:
                self.font_index += n
                try:
                    font = self.fonts[self.font_index]
                except IndexError:
                    if n > 0:
                        self.font_index = 0
                        font = self.fonts[self.font_index]
                    else:
                        self.font_index = len(self.fonts)
                        font = self.fonts[self.font_index]
        else:
            while font not in shortlist:
                self.font_index += n
                try:
                    font = self.fonts[self.font_index]
                except IndexError:
                    if n > 0:
                        self.font_index = 0
                        font = self.fonts[self.font_index]
                    else:
                        self.font_index = len(self.fonts)
                        font = self.fonts[self.font_index]

        item.configure(font=(font, size))
        print(f"Font: {font}")

    def shortlist_font(self):
        self.font_shortlist += [self.fonts[self.font_index]]
        self.font_shortlist = list(set(self.font_shortlist))
        print("Font Shortlist:")
        [print(f"{i}:{font}") for i, font in enumerate(self.font_shortlist)]

    def save_game(self):
        """:cvar
        progress is the current line for each text the user is one
        history is the summmary of each attempt made.
            - eventtime
            - duration
            - accuracy
            - wpm
            - guess
            - answer
            - match
        """
        game_settings = {
            "Texts": {self.text.name: {"line": self.text.position}},
            "History": self.game_history,
        }
        with open(self.save_fname, "wb") as save_file:
            pickle.dump(game_settings, save_file)
        if self.DEBUG:
            print("SAVED GAME")

    def load_game(self):
        """
        Open the save game
        :return:
        """

        with open(self.save_fname, "rb") as save_file:
            self.game_settings = pickle.load(save_file)
        self.text.position = self.game_settings["Texts"][self.text.name]["line"]
        self.game_history = self.game_settings["History"]
        # self.game_history = dict() # CLEAR
        print(f"Game Loaded: \n{self.game_settings['Texts']}")
        print(f"{len(self.game_history)} history entries loaded")
        try:
            print(
                f"Last History Entry: \n{self.game_history[max([key for key in self.game_history])]}"
            )
        except ValueError:
            print(f"Last History Entry: None")

    def set_state(self, new_state):
        valid_game_states = ["INIT", "READY", "GAME"]
        if new_state in valid_game_states:
            self.state = new_state
        else:
            raise ValueError(f"Tried to set invalid GameState: {new_state}")

        if self.state == "READY":
            self.user_input = ""
            self.user_input_full = ""
            # self.draw_userinput()
            self.instructions["text"] = "Press Enter to start."

        if self.state == "GAME":
            # self.instructions['text'] = ''
            self.instructions["text"] = f"Press Enter to finish or Esc to exit."
            if self.results_str != "":
                self.instructions["text"] += f" Prev Result: {self.results_str}"

        if self.DEBUG:
            print(f"GameState: {self.state}")

    def key_handler(self, event):
        DEBUG = False

        if DEBUG:
            print(
                f"KeyPress - Char:{event.char:1}, Keysym:{event.keysym:8}, Keycode:{event.keycode:4}, State:{event.state:2}"
            )
            # f"\tUser Input: '{self.user_input}', len: {len(self.user_input)}")

        if self.state == "READY":
            if event.keycode == 13:  # Enter
                self.set_state("GAME")

        elif self.state == "GAME":
            if event.state == 4:  # Control is being pressed with this key
                if event.keysym == "BackSpace":
                    self.user_input = " ".join(self.user_input.split()[:-1])
                if event.keysym == "q":
                    exit()
            else:
                if event.keycode == 13:  # Enter
                    self.calc_typing_stats()
                    self.user_input = ""
                    self.user_input_full = ""
                    self.time_start = datetime.now()
                elif event.keycode == 27:  # ESC
                    self.user_input = ""
                    self.user_input_full = ""
                    self.set_state("READY")
                elif event.keycode == 8:  # Backspace
                    self.user_input = self.user_input[:-1]
                    self.user_input_full += event.char
                else:
                    if self.user_input == "":
                        self.time_start = datetime.now()
                    self.user_input += event.char
                    self.user_input_full += event.char

            # self.draw_userinput()
            self.draw_textbox()

    def log_game_history(self, results):
        self.game_history[self.time_start] = {
            "EventTime": f"{self.time_start:%d-%m-%Y %H:%M:%S}",
            "TextName": self.text.name,
            "Length": len(self.text.get_current_line()),
            "Duration": results["duration"],
            "Accuracy": results["accuracy"],
            "Wpm": results["wpm"],
            "Answer": self.text.get_current_line(),
            "user_input": self.user_input,
            "user_input_full": self.user_input_full,
        }

    def clear_game_history(self, TextName="All"):
        """
        Reset the game_history. If specified will only remove the passed Text
        """
        if TextName == "All":
            self.game_history = dict()
        else:
            self.game_history = {
                key: vals
                for key, vals in self.game_history.items()
                if vals["TextName"] != TextName
            }

    def passing_grade(self, results):
        if results["accuracy"] < 1:
            return False
        elif results["accuracy"] == 1:
            return True
        else:
            raise ValueError(f"results['accuracy'] > 100% - {results['accuracy']:=}")

    def calc_typing_stats(self):
        results = dict()
        results["duration"] = datetime.now() - self.time_start
        results["duration"] = round(
            (results["duration"].seconds + results["duration"].microseconds / 1e6), 3
        )  # round to the millisecond
        results = typing_score(
            self.user_input, self.text.get_current_line(), results["duration"]
        )

        if self.passing_grade(results):
            grade = "PASS"
            self.log_game_history(results)
            self.text.position += 1
            self.draw_textbox()
            self.save_game()
            self.results_str = f"Wpm: {results['wpm']:.2f}"
        else:
            grade = "FAIL"
            self.log_game_history(results)
            print(f"FAIL, not 100% accurate:")
            print(f"Text: {self.text.get_current_line()}")
            print(f"User: {self.user_input}")
            print(f"Diff: {''.join([str(int(char)) for char in results['matches']])}")
            self.results_str = f"{grade} - Accuracy: {results['accuracy']:.2%}, {results['wpm']:.2f} wpm."

        self.instructions["text"] = (
            f"Press Enter to finish or Esc to exit. Prev Result: {self.results_str}"
        )
        print(self.results_str)

    def draw_textbox(self):
        nl = "\n"
        pos = self.text.position
        self.text_box.configure(state="normal")
        self.text_box.delete(1.0, "end")  # clear
        self.text_box.insert(
            1.0, nl.join(self.text.contents[pos : pos + self.display_nlines])
        )

        matches = compare_lines(guess=self.user_input, answer=self.text.contents[pos])
        correct_chars = len(
            "".join(["1" if val else "0" for val in matches]).split("0")[0]
        )
        self.text_box.tag_add("correct", "1.0", f"1.{correct_chars:.0f}")
        self.text_box.tag_add(
            "incorrect", f"1.{correct_chars:.0f}", f"1.{len(self.user_input):.0f}"
        )
        self.text_box.tag_add("next_line", "2.0", f"{2 + self.display_nlines:.0f}.20")

        self.text_box.tag_config("correct", foreground="green")
        self.text_box.tag_config("incorrect", foreground="red")
        self.text_box.tag_config("next_line", foreground="grey")

        self.text_box.configure(state="disabled")

    def draw_userinput(self):
        self.userinput_box.configure(state="normal")
        self.userinput_box.delete(1.0, "end")  # clear
        self.userinput_box.insert(1.0, f"{self.user_input}")  # new user input
        self.userinput_box.configure(state="disabled")

    def change_pos(self, n):
        self.text.position += n
        self.draw_textbox()
        self.set_state("READY")
