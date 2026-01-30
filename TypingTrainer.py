import tkinter as tk
from PIL import Image, ImageTk
from os import path, getcwd
from datetime import datetime
import shutil
import pickle  # for loading and saving game info
import json
from sys import exit
from Texts import Text
from functions import *
import ctypes


class Game:

    def __init__(self, root, window_width=1200, window_height=500):
        """Initialize the TypingTrainer game.

        Args:
            root: The tkinter root window
            window_width: Width of the game window in pixels (default: 1200)
            window_height: Height of the game window in pixels (default: 500)
        """
        self.DEBUG = False
        self.root_dir = getcwd()
        self.texts_dir = path.join(self.root_dir, "Texts")
        self.root = root
        self.root.title("TypingTrainer")

        # Set Windows taskbar icon
        try:
            # Set AppUserModelID to make Windows recognize this as a unique app
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "TypingTrainer.App"
            )
            self.root.iconbitmap("Images/TyperTrainer.ico")
        except:
            # Fallback to PNG if .ico doesn't exist or on non-Windows
            icon_image = tk.PhotoImage(file="Images/TyperTrainer.png")
            self.root.tk.call("wm", "iconphoto", root._w, icon_image)
        self.width = window_width
        self.height = window_height
        self.display_nlines = 5

        self.state = str()
        self.user_input = ""
        self.user_input_full = ""
        self.results_str = ""

        self.config_fname = path.join(self.root_dir, "config.json")
        self.require_accuracy = True
        self.require_wpm = True
        self.min_accuracy = 1.0
        self.min_wpm = 20.0
        self.show_criteria = True
        self.flash_on_mistake = True  # New: default enabled
        self.load_config()

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
        text_style = ("Roboto", 20)  # font settings for text box
        textname_style = ("Raleway", 30)
        textposition_style = ("Raleway", 14)
        title_style = ("Eras Medium ITC", 60)
        button_style = ("Raleway", 12)

        acc_primary_c = "#20bebe"
        acc_primary_fc = "white"

        # menu
        self.menu_bar = tk.Menu(root)
        file_menu = tk.Menu(self.menu_bar, tearoff=0)

        # Select Text submenu
        self.select_text_menu = tk.Menu(file_menu, tearoff=0)
        self._populate_text_menu()
        file_menu.add_cascade(label="Select Text", menu=self.select_text_menu)

        file_menu.add_command(label="Load New Text", command=self.load_text)

        criteria_menu = tk.Menu(file_menu, tearoff=0)
        self.require_accuracy_var = tk.BooleanVar(value=self.require_accuracy)
        self.require_wpm_var = tk.BooleanVar(value=self.require_wpm)
        self.show_criteria_var = tk.BooleanVar(value=self.show_criteria)
        self.flash_on_mistake_var = tk.BooleanVar(value=self.flash_on_mistake)
        criteria_menu.add_checkbutton(
            label="Show Criteria",
            variable=self.show_criteria_var,
            command=self.toggle_show_criteria,
        )
        criteria_menu.add_separator()
        criteria_menu.add_checkbutton(
            label="Require Accuracy",
            variable=self.require_accuracy_var,
            command=self.toggle_require_accuracy,
        )
        criteria_menu.add_checkbutton(
            label="Require WPM",
            variable=self.require_wpm_var,
            command=self.toggle_require_wpm,
        )
        criteria_menu.add_separator()
        criteria_menu.add_checkbutton(
            label="Flash on Mistake",
            variable=self.flash_on_mistake_var,
            command=self.toggle_flash_on_mistake,
        )
        criteria_menu.add_separator()
        criteria_menu.add_command(
            label="Set Min Accuracy",
            command=self.set_min_accuracy,
        )
        criteria_menu.add_command(
            label="Set Min WPM",
            command=self.set_min_wpm,
        )
        file_menu.add_cascade(label="Passing Criteria", menu=criteria_menu)
        file_menu.add_separator()
        # file_menu.add_command(label="Reset History", command=self.reset_history)
        self.menu_bar.add_cascade(label="Settings", menu=file_menu)
        root.config(menu=self.menu_bar)

        # logo image
        logo = ImageTk.PhotoImage(Image.open(r"Images\TyperTrainerMascot_30.png"))
        self.logo_label = tk.Label(image=logo)
        self.logo_label.image = logo
        self.logo_label.grid(column=2, row=0)

        # Text name frame (contains name and position labels)
        textname_frame = tk.Frame(root)
        textname_frame.grid(column=0, row=0)

        self.textname = tk.Label(
            textname_frame,
            text=f'"{self.text.name}"',
            font=textname_style,
        )
        self.textname.pack()

        # Text position info
        self.textposition = tk.Label(
            textname_frame,
            text=f"{self.text.position}/{self.text.lines} ({self.text.position/self.text.lines:.1%})",
            font=textposition_style,
            cursor="hand2",
        )
        self.textposition.bind("<Button-1>", self.prompt_page_jump)
        self.textposition.pack()

        # Passing criteria display
        self.accuracy_label = tk.Label(
            textname_frame,
            text="",
            font=textposition_style,
            cursor="hand2",
        )
        self.accuracy_label.bind("<Button-1>", lambda event: self.set_min_accuracy())
        self.accuracy_label.pack()

        self.wpm_label = tk.Label(
            textname_frame,
            text="",
            font=textposition_style,
            cursor="hand2",
        )
        self.wpm_label.bind("<Button-1>", lambda event: self.set_min_wpm())
        self.wpm_label.pack()

        self.update_criteria_labels()

        # Flash label for mistakes
        self.flash_label = tk.Label(
            root, text="fuck", font=("Arial", 48), fg="red", bg="yellow"
        )
        self.flash_label.place(relx=0.5, rely=0.5, anchor="center")
        self.flash_label.lower()  # Hide initially

        # Title
        self.title = tk.Label(root, text=f"Typing Trainer", font=title_style)
        self.title.grid(column=1, row=0)

        # page input
        self.text_box = tk.Text(
            root,
            height=self.display_nlines,
            width=int(self.width * 0.06),
            padx=5,
            pady=5,
            font=text_style,
        )
        self.text_box.grid(column=0, row=1, columnspan=3)
        self.text_box.config(wrap="word")
        self.draw_textbox()

        # Instructions frame (contains caps lock indicator and instructions)
        instructions_frame = tk.Frame(root)
        instructions_frame.grid(column=1, row=2)

        # caps lock indicator
        self.capslock_indicator = tk.Label(
            instructions_frame, text="", font=("Raleway", 10), fg="orange"
        )
        self.capslock_indicator.pack()

        # instructions
        self.instructions = tk.Label(
            instructions_frame, text="Press Enter to start", font="Raleway"
        )
        self.instructions.pack()

        # prev line button
        browse_text = tk.StringVar()
        self.prev_btn = tk.Button(
            root,
            textvariable=browse_text,
            command=lambda: self.change_pos(-1),
            font=button_style,
            bg=acc_primary_c,
            fg=acc_primary_fc,
            height=1,
            width=10,
            takefocus=0,
        )
        browse_text.set("Prev")
        self.prev_btn.grid(column=0, row=2)

        # next line button
        browse_text = tk.StringVar()
        self.next_btn = tk.Button(
            root,
            textvariable=browse_text,
            command=lambda: self.change_pos(1),
            font=button_style,
            bg=acc_primary_c,
            fg=acc_primary_fc,
            height=1,
            width=10,
            takefocus=0,
        )
        browse_text.set("Next")
        self.next_btn.grid(column=2, row=2)

        #################################
        # ---------- STARTUP ---------- #
        #################################

        root.bind("<Key>", self.key_handler)
        self.time_start = datetime.now()
        self.set_state("READY")

    def save_game(self):
        """Save the current game state to a pickle file.

        Saves:
            - Current text position for each text
            - Game history with attempt details (eventtime, duration, accuracy, wpm, etc.)
        """
        game_settings = {
            "Texts": {self.text.name: {"line": self.text.position}},
            "History": self.game_history,
        }
        with open(self.save_fname, "wb") as save_file:
            pickle.dump(game_settings, save_file)
        if self.DEBUG:
            print("SAVED GAME")

    def load_config(self):
        """Load configuration from a human-readable JSON file."""
        if not path.exists(self.config_fname):
            self.save_config()
            return
        try:
            with open(self.config_fname, "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
            self.require_accuracy = bool(config.get("require_accuracy", True))
            self.require_wpm = bool(config.get("require_wpm", True))
            self.min_accuracy = float(config.get("min_accuracy", 1.0))
            self.min_wpm = float(config.get("min_wpm", 20.0))
            self.show_criteria = bool(config.get("show_criteria", True))
            self.flash_on_mistake = bool(config.get("flash_on_mistake", True))
            if hasattr(self, 'flash_on_mistake_var'):
                self.flash_on_mistake_var.set(self.flash_on_mistake)
        except (json.JSONDecodeError, OSError, ValueError):
            self.save_config()

    def save_config(self):
        """Save configuration to a human-readable JSON file."""
        config = {
            "require_accuracy": self.require_accuracy,
            "require_wpm": self.require_wpm,
            "min_accuracy": round(float(self.min_accuracy), 4),
            "min_wpm": round(float(self.min_wpm), 2),
            "show_criteria": self.show_criteria,
            "flash_on_mistake": self.flash_on_mistake,
        }
        with open(self.config_fname, "w", encoding="utf-8") as config_file:
            json.dump(config, config_file, indent=2)
    def toggle_flash_on_mistake(self):
        self.flash_on_mistake = bool(self.flash_on_mistake_var.get())
        self.save_config()

    def toggle_show_criteria(self):
        self.show_criteria = bool(self.show_criteria_var.get())
        self.save_config()
        self.update_criteria_labels()

    def toggle_require_accuracy(self):
        self.require_accuracy = bool(self.require_accuracy_var.get())
        self.save_config()
        self.update_criteria_labels()

    def toggle_require_wpm(self):
        self.require_wpm = bool(self.require_wpm_var.get())
        self.save_config()
        self.update_criteria_labels()

    def set_min_accuracy(self):
        value = tk.simpledialog.askfloat(
            "Minimum Accuracy",
            "Enter minimum accuracy (0-100):",
            parent=self.root,
            minvalue=0.0,
            maxvalue=100.0,
        )
        if value is None:
            return
        self.min_accuracy = max(0.0, min(1.0, value / 100.0))
        self.save_config()
        self.update_criteria_labels()

    def set_min_wpm(self):
        value = tk.simpledialog.askfloat(
            "Minimum WPM",
            "Enter minimum words per minute:",
            parent=self.root,
            minvalue=0.0,
        )
        if value is None:
            return
        self.min_wpm = max(0.0, float(value))
        self.save_config()
        self.update_criteria_labels()

    def update_criteria_labels(self):
        self.accuracy_label.pack_forget()
        self.wpm_label.pack_forget()

        if not self.show_criteria:
            return

        if self.require_accuracy:
            self.accuracy_label.config(text=f"Min Acc: {self.min_accuracy:.0%}")
            self.accuracy_label.pack()

        if self.require_wpm:
            self.wpm_label.config(text=f"Min WPM: {self.min_wpm:.0f}")
            self.wpm_label.pack()

    def _populate_text_menu(self):
        """Populate the Select Text submenu with available texts."""
        self.select_text_menu.delete(0, tk.END)
        for text_name in self.available_texts.keys():
            self.select_text_menu.add_command(
                label=text_name,
                command=lambda name=text_name: self._set_active_text(
                    name, self.available_texts[name]
                ),
            )

    def load_text(self):
        """Load a text file from disk and add it to available texts."""
        import os

        # Get all .txt files from the Texts directory
        txt_files = [f for f in os.listdir(self.texts_dir) if f.endswith(".txt")]

        if not txt_files:
            self.instructions["text"] = "No text files found in Texts folder."
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Load Text")
        dialog.resizable(False, False)

        # Center the dialog
        dialog.update_idletasks()
        x = (
            self.root.winfo_x()
            + (self.root.winfo_width() // 2)
            - (dialog.winfo_width() // 2)
        )
        y = (
            self.root.winfo_y()
            + (self.root.winfo_height() // 2)
            - (dialog.winfo_height() // 2)
        )
        dialog.geometry(f"+{x}+{y}")

        selected_file = tk.StringVar(value=txt_files[0])
        tk.Label(dialog, text="Select text file:").grid(
            column=0, row=0, padx=10, pady=10
        )
        option_menu = tk.OptionMenu(dialog, selected_file, *txt_files)
        option_menu.config(width=30)
        option_menu.grid(column=1, row=0, padx=10, pady=10)

        def apply_selection():
            filename = selected_file.get()
            text_name = path.splitext(filename)[0]
            self.available_texts[text_name] = filename
            self._set_active_text(text_name, filename)
            self._populate_text_menu()  # Refresh the menu
            dialog.destroy()

        tk.Button(dialog, text="Load", command=apply_selection).grid(
            column=0, row=1, columnspan=2, pady=(0, 10)
        )

        dialog.transient(self.root)
        dialog.grab_set()
        dialog.wait_window()

    def reset_history(self):
        """Reset game history for the current text and save the game."""
        self.clear_game_history(TextName=self.text.name)
        self.save_game()
        self.instructions["text"] = "History reset. Press Enter to start."

    def _set_active_text(self, text_name, text_location):
        """Set and load the active text, then refresh UI elements."""
        self.text = Text(text_name, text_location)
        self.text.load(self.texts_dir)
        self.game_settings["Texts"] = {self.text.name: {"line": self.text.position}}
        self.textname.config(text=f'"{self.text.name}"')
        self.draw_textbox()
        self.update_position_label()
        self.set_state("READY")

    def load_game(self):
        """Load the saved game state from a pickle file.

        Restores the text position and game history from the save file.
        Prints loading status and last history entry to console.
        """

        with open(self.save_fname, "rb") as save_file:
            self.game_settings = pickle.load(save_file)
        self.text.position = self.game_settings["Texts"][self.text.name]["line"]
        self.game_history = self.game_settings["History"]
        print(f"Game Loaded: \n{self.game_settings['Texts']}")
        print(f"{len(self.game_history)} history entries loaded")
        try:
            print(
                f"Last History Entry: \n{self.game_history[max([key for key in self.game_history])]}"
            )
        except ValueError:
            print(f"Last History Entry: None")

    def set_state(self, new_state):
        """Set the game state and update UI accordingly.

        Args:
            new_state: New game state, must be one of: "INIT", "READY", or "GAME"

        Raises:
            ValueError: If new_state is not a valid game state
        """
        valid_game_states = ["INIT", "READY", "GAME"]
        if new_state in valid_game_states:
            self.state = new_state
        else:
            raise ValueError(f"Tried to set invalid GameState: {new_state}")

        if self.state == "READY":
            self.user_input = ""
            self.user_input_full = ""
            self.instructions["text"] = "Press Enter to start."
            self.prev_btn.config(takefocus=1)
            self.next_btn.config(takefocus=1)

        if self.state == "GAME":
            self.instructions["text"] = f"Press Enter to finish or Esc to exit."
            if self.results_str != "":
                self.instructions["text"] += f" Prev {self.results_str}"
            self.prev_btn.config(takefocus=0)
            self.next_btn.config(takefocus=0)
            # Remove focus from buttons if they have it
            self.root.focus_set()

        if self.DEBUG:
            print(f"GameState: {self.state}")

    def flash_mistake(self):
        self.flash_label.lift()
        self.root.after(300, self.flash_label.lower)

    def key_handler(self, event):
        """Handle all keyboard input events.

        Processes key presses based on current game state:
        - READY: Enter to start game
        - GAME: Typing input, Enter to finish, ESC to exit, Ctrl+Backspace to delete word
        - Global: Ctrl+Q to quit

        Also updates caps lock indicator based on keyboard state.

        Args:
            event: tkinter keyboard event object
        """
        DEBUG = False

        # Check caps lock state (bit 2 in event.state for Caps Lock)
        caps_on = bool(event.state & 0x2)

        # If Caps Lock key is pressed, the state toggles, so we need to invert our check
        if event.keysym == "Caps_Lock":
            caps_on = not caps_on

        if caps_on:
            self.capslock_indicator.config(text="⚠ CAPS LOCK ON")
        else:
            self.capslock_indicator.config(text="")

        if DEBUG:
            print(
                f"KeyPress - Char:{event.char:1}, Keysym:{event.keysym:8}, Keycode:{event.keycode:4}, State:{event.state:2}"
            )

        # Handle Ctrl+Q globally (in all states)
        if (event.state & 0x4) and event.keysym == "q":
            exit()

        if self.state == "READY":
            if event.keycode == 13:  # Enter
                self.set_state("GAME")

        elif self.state == "GAME":
            if (
                event.state & 0x4
            ):  # Control is being pressed with this key (bitwise check)
                if event.keysym == "BackSpace":
                    self.user_input = " ".join(self.user_input.split()[:-1]) + " "
                    self.draw_textbox()
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
                    # Check for mistake
                    target_line = self.text.get_current_line()
                    next_index = len(self.user_input)
                    if (
                        self.flash_on_mistake
                        and next_index < len(target_line)
                        and event.char
                        and event.char != target_line[next_index]
                    ):
                        self.flash_mistake()
                    self.user_input += event.char
                    self.user_input_full += event.char

            self.draw_textbox()

    def log_game_history(self, results):
        """Log typing attempt results to game history.

        Args:
            results: Dictionary containing typing statistics (duration, accuracy, wpm, etc.)
        """
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
        """Reset the game history.

        Args:
            TextName: Name of specific text to clear history for, or "All" to clear all history (default: "All")
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
        """Determine if typing attempt meets passing criteria.

        Args:
            results: Dictionary containing accuracy metric

        Returns:
            bool: True if accuracy is 100%, False otherwise

        Raises:
            ValueError: If accuracy exceeds 100%
        """
        if self.require_accuracy:
            if results["accuracy"] > 1:
                raise ValueError(
                    f"results['accuracy'] > 100% - {results['accuracy']:=}"
                )
            if results["accuracy"] < self.min_accuracy:
                return False

        if self.require_wpm and results["wpm"] < self.min_wpm:
            return False

        return True

    def calc_typing_stats(self):
        """Calculate typing statistics and handle pass/fail logic.

        Computes duration, accuracy, and WPM for the current attempt.
        If passing grade: logs history, advances position, and saves game.
        If failing: logs history and displays error details.
        Updates the results display and instructions text.
        """
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
            self.update_position_label()
            self.save_game()
            self.results_str = (
                f"Wpm: {results['wpm']:.0f}, Acc: {results['accuracy']:.1%}"
            )
        else:
            grade = "FAIL"
            self.log_game_history(results)
            print(f"FAIL, not 100% accurate:")
            print(f"Text: {self.text.get_current_line()}")
            print(f"User: {self.user_input}")
            print(f"Diff: {''.join([str(int(char)) for char in results['matches']])}")
            self.results_str = (
                f"{grade} - Acc: {results['accuracy']:.0%}, {results['wpm']:.0f} wpm."
            )

        self.instructions["text"] = (
            f"Press Enter to finish or Esc to exit. Prev: {self.results_str}"
        )
        print(self.results_str)

    def draw_textbox(self):
        """Update the text box display with current text and user input feedback.

        Shows the current line and upcoming lines from the text.
        Highlights correct characters in green and incorrect characters in red.
        Displays upcoming lines in grey.
        """
        nl = "\n"
        pos = self.text.position
        self.text_box.configure(state="normal")
        self.text_box.delete(1.0, "end")  # clear
        visible_lines = self.text.contents[pos : pos + self.display_nlines]
        if not visible_lines:
            self.text_box.configure(state="disabled")
            return

        target_line = visible_lines[0]
        if len(self.user_input) <= len(target_line):
            display_first = self.user_input + target_line[len(self.user_input) :]
        else:
            display_first = self.user_input

        visible_lines = [display_first] + visible_lines[1:]
        self.text_box.insert(1.0, nl.join(visible_lines))

        for index, typed_char in enumerate(self.user_input):
            target_char = target_line[index] if index < len(target_line) else None
            if target_char is not None and typed_char == target_char:
                tag = "correct"
            else:
                tag = "incorrect"
            self.text_box.tag_add(tag, f"1.{index}", f"1.{index + 1}")

            if tag == "incorrect" and (typed_char == " " or target_char == " "):
                self.text_box.tag_add("incorrect_space", f"1.{index}", f"1.{index + 1}")

        self.text_box.tag_add("next_line", "2.0", "end")

        self.text_box.tag_config("correct", foreground="green")
        self.text_box.tag_config("incorrect", foreground="red")
        self.text_box.tag_config("next_line", foreground="grey")
        self.text_box.tag_config("incorrect_space", foreground="red", underline=True)

        self.text_box.configure(state="disabled")

    def change_pos(self, n):
        """Change the current text position.

        Args:
            n: Number of lines to move (positive for forward, negative for backward)
        """
        self.text.position += n
        self.draw_textbox()
        self.update_position_label()
        self.set_state("READY")

    def update_position_label(self):
        """Update the position label to display current line number and progress percentage."""
        self.textposition.config(
            text=f"{self.text.position}/{self.text.lines} ({self.text.position/self.text.lines:.1%})"
        )

    def prompt_page_jump(self, event=None):
        """Prompt for a page number and jump to that line if valid."""
        if self.text.lines <= 0:
            return
        selected_page = tk.simpledialog.askinteger(
            "Go to page",
            f"Enter page number (1-{self.text.lines}):",
            parent=self.root,
            minvalue=1,
            maxvalue=self.text.lines,
        )
        if selected_page is None:
            return
        self.text.position = selected_page - 1
        self.draw_textbox()
        self.update_position_label()
        self.set_state("READY")


if __name__ == "__main__":
    import tkinter as tk
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
