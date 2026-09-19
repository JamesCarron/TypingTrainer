"""The tkinter front end: widgets only, driving a Session.

This is the widget half of the old ``Game`` class. Everything it used to do
itself — scoring, history, config, position — now goes through
``typingtrainer.session.Session``, so the desktop app and the web app cannot
drift apart. Anything in here that is not a widget, a key binding or a dialog
is in the wrong file.

Written 2026-09-19 during the stage 3 engine extraction (docs/Refactor_Plan.md).
Verified by playing through lines in the real window; the engine underneath is
covered by tests/test_session.py.
"""

import ctypes
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import simpledialog

from PIL import Image, ImageTk

from ..session import Session
from .window import setup_window

IMG_DIR = Path(__file__).resolve().parent.parent / "static" / "img"


class Game:
    """The tkinter view. One window, one Session."""

    def __init__(self, root, window_width=1200, window_height=500, session=None):
        self.session = session if session is not None else Session()
        self.root = root
        self.root.title("TypingTrainer")
        self.width = window_width
        self.height = window_height
        self.display_nlines = self.session.display_lines

        self.user_input = ""
        self.user_input_full = ""
        self.results_str = ""
        self.time_start = datetime.now()
        # Per-keystroke record for the analysis; see history.append_attempt. The web
        # view captures the same list, so both front ends feed one dataset.
        self.keystrokes = []

        self._set_icon()
        self._build_menu()
        self._build_widgets()

        root.bind("<Key>", self.key_handler)
        self.refresh_state()

    # ---- chrome ------------------------------------------------------------

    def _set_icon(self):
        try:
            # Makes Windows treat this as its own app rather than "python.exe",
            # which is what gives it its own taskbar icon.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "TypingTrainer.App"
            )
            self.root.iconbitmap(str(IMG_DIR / "TyperTrainer.ico"))
        except Exception:
            icon_image = tk.PhotoImage(file=str(IMG_DIR / "TyperTrainer.png"))
            self.root.tk.call("wm", "iconphoto", self.root._w, icon_image)

    def _build_menu(self):
        self.menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(self.menu_bar, tearoff=0)

        self.select_text_menu = tk.Menu(file_menu, tearoff=0)
        self._populate_text_menu()
        file_menu.add_cascade(label="Select Text", menu=self.select_text_menu)
        file_menu.add_command(label="Add Text From File", command=self.add_text)

        s = self.session.settings
        criteria_menu = tk.Menu(file_menu, tearoff=0)
        self.require_accuracy_var = tk.BooleanVar(value=s.require_accuracy)
        self.require_wpm_var = tk.BooleanVar(value=s.require_wpm)
        self.show_criteria_var = tk.BooleanVar(value=s.show_criteria)
        self.flash_on_mistake_var = tk.BooleanVar(value=s.flash_on_mistake)
        self.stop_on_error_var = tk.BooleanVar(value=s.stop_on_error)
        criteria_menu.add_checkbutton(
            label="Show Criteria",
            variable=self.show_criteria_var,
            command=lambda: self._apply_setting(show_criteria=self.show_criteria_var.get()),
        )
        criteria_menu.add_separator()
        criteria_menu.add_checkbutton(
            label="Require Accuracy",
            variable=self.require_accuracy_var,
            command=lambda: self._apply_setting(
                require_accuracy=self.require_accuracy_var.get()
            ),
        )
        criteria_menu.add_checkbutton(
            label="Require WPM",
            variable=self.require_wpm_var,
            command=lambda: self._apply_setting(require_wpm=self.require_wpm_var.get()),
        )
        criteria_menu.add_separator()
        criteria_menu.add_checkbutton(
            label="Flash on Mistake",
            variable=self.flash_on_mistake_var,
            command=lambda: self._apply_setting(
                flash_on_mistake=self.flash_on_mistake_var.get()
            ),
        )
        criteria_menu.add_checkbutton(
            label="Stop on Mistake",
            variable=self.stop_on_error_var,
            command=lambda: self._apply_setting(
                stop_on_error=self.stop_on_error_var.get()
            ),
        )
        criteria_menu.add_separator()
        criteria_menu.add_command(label="Set Min Accuracy", command=self.set_min_accuracy)
        criteria_menu.add_command(label="Set Min WPM", command=self.set_min_wpm)
        file_menu.add_cascade(label="Passing Criteria", menu=criteria_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Reset History (this text)", command=self.reset_history)
        self.menu_bar.add_cascade(label="Settings", menu=file_menu)
        self.root.config(menu=self.menu_bar)

    def _build_widgets(self):
        text_style = ("Roboto", 20)
        textname_style = ("Raleway", 30)
        textposition_style = ("Raleway", 14)
        title_style = ("Eras Medium ITC", 60)
        button_style = ("Raleway", 12)
        acc_primary_c = "#20bebe"
        acc_primary_fc = "white"

        logo = ImageTk.PhotoImage(Image.open(IMG_DIR / "TyperTrainerMascot_30.png"))
        self.logo_label = tk.Label(image=logo)
        self.logo_label.image = logo
        self.logo_label.grid(column=2, row=0)

        textname_frame = tk.Frame(self.root)
        textname_frame.grid(column=0, row=0)

        self.textname = tk.Label(
            textname_frame, text=f'"{self.session.text_name}"', font=textname_style
        )
        self.textname.pack()

        self.textposition = tk.Label(
            textname_frame, text="", font=textposition_style, cursor="hand2"
        )
        self.textposition.bind("<Button-1>", self.prompt_page_jump)
        self.textposition.pack()

        self.accuracy_label = tk.Label(
            textname_frame, text="", font=textposition_style, cursor="hand2"
        )
        self.accuracy_label.bind("<Button-1>", lambda event: self.set_min_accuracy())
        self.accuracy_label.pack()

        self.wpm_label = tk.Label(
            textname_frame, text="", font=textposition_style, cursor="hand2"
        )
        self.wpm_label.bind("<Button-1>", lambda event: self.set_min_wpm())
        self.wpm_label.pack()

        # Mistake flash: a wordless marker. It used to be a shouted expletive,
        # dropped when the repo went public.
        self.flash_label = tk.Label(
            self.root, text="✗", font=("Arial", 48), fg="red", bg="yellow"
        )
        self.flash_label.place(relx=0.5, rely=0.5, anchor="center")
        self.flash_label.lower()

        self.title = tk.Label(self.root, text="Typing Trainer", font=title_style)
        self.title.grid(column=1, row=0)

        self.text_box = tk.Text(
            self.root,
            height=self.display_nlines,
            width=int(self.width * 0.06),
            padx=5,
            pady=5,
            font=text_style,
        )
        self.text_box.grid(column=0, row=1, columnspan=3)
        self.text_box.config(wrap="word")

        instructions_frame = tk.Frame(self.root)
        instructions_frame.grid(column=1, row=2)
        self.capslock_indicator = tk.Label(
            instructions_frame, text="", font=("Raleway", 10), fg="orange"
        )
        self.capslock_indicator.pack()
        self.instructions = tk.Label(
            instructions_frame, text="Press Enter to start", font="Raleway"
        )
        self.instructions.pack()

        self.prev_btn = tk.Button(
            self.root,
            text="Prev",
            command=lambda: self.change_pos(-1),
            font=button_style,
            bg=acc_primary_c,
            fg=acc_primary_fc,
            height=1,
            width=10,
            takefocus=0,
        )
        self.prev_btn.grid(column=0, row=2)

        self.next_btn = tk.Button(
            self.root,
            text="Next",
            command=lambda: self.change_pos(1),
            font=button_style,
            bg=acc_primary_c,
            fg=acc_primary_fc,
            height=1,
            width=10,
            takefocus=0,
        )
        self.next_btn.grid(column=2, row=2)

        self.update_criteria_labels()
        self.draw_textbox()
        self.update_position_label()

    # ---- settings ----------------------------------------------------------

    def _apply_setting(self, **kwargs):
        self.session.update_settings(**kwargs)
        self.update_criteria_labels()

    def set_min_accuracy(self):
        value = simpledialog.askfloat(
            "Minimum Accuracy",
            "Enter minimum accuracy (0-100):",
            parent=self.root,
            minvalue=0.0,
            maxvalue=100.0,
        )
        if value is None:
            return
        self._apply_setting(min_accuracy=value / 100.0)

    def set_min_wpm(self):
        value = simpledialog.askfloat(
            "Minimum WPM",
            "Enter minimum words per minute:",
            parent=self.root,
            minvalue=0.0,
        )
        if value is None:
            return
        self._apply_setting(min_wpm=value)

    def update_criteria_labels(self):
        self.accuracy_label.pack_forget()
        self.wpm_label.pack_forget()
        s = self.session.settings
        if not s.show_criteria:
            return
        if s.require_accuracy:
            self.accuracy_label.config(text=f"Min Acc: {s.min_accuracy:.0%}")
            self.accuracy_label.pack()
        if s.require_wpm:
            self.wpm_label.config(text=f"Min WPM: {s.min_wpm:.0f}")
            self.wpm_label.pack()

    # ---- text library ------------------------------------------------------

    def _populate_text_menu(self):
        self.select_text_menu.delete(0, tk.END)
        for name in self.session.snapshot()["texts"]:
            label = name["name"]
            self.select_text_menu.add_command(
                label=label, command=lambda n=label: self._select_text(n)
            )

    def _select_text(self, name):
        self.session.select_text(name)
        self.textname.config(text=f'"{self.session.text_name}"')
        self.refresh_state()

    def add_text(self):
        """Copy a .txt into the user's library, then switch to it."""
        from tkinter.filedialog import askopenfilename

        chosen = askopenfilename(
            parent=self.root,
            title="Add a text",
            filetypes=[("Text files", "*.txt")],
        )
        if not chosen:
            return
        name = self.session.add_text(chosen)
        self._populate_text_menu()
        self._select_text(name)

    def reset_history(self):
        removed = self.session.reset_history("current")
        self.instructions["text"] = f"History reset ({removed} records). Press Enter to start."

    # ---- state -------------------------------------------------------------

    def refresh_state(self):
        """Repaint everything the session's state implies."""
        if self.session.state == "READY":
            self.user_input = ""
            self.user_input_full = ""
            self.keystrokes = []
            self.instructions["text"] = "Press Enter to start."
            self.prev_btn.config(takefocus=1)
            self.next_btn.config(takefocus=1)
        else:
            text = "Press Enter to finish or Esc to exit."
            if self.results_str:
                text += f" Prev {self.results_str}"
            self.instructions["text"] = text
            self.prev_btn.config(takefocus=0)
            self.next_btn.config(takefocus=0)
            self.root.focus_set()
        self.draw_textbox()
        self.update_position_label()

    def flash_mistake(self):
        self.flash_label.lift()
        self.root.after(300, self.flash_label.lower)

    def key_handler(self, event):
        """Every key press, dispatched on the session's state."""
        caps_on = bool(event.state & 0x2)
        if event.keysym == "Caps_Lock":
            caps_on = not caps_on
        self.capslock_indicator.config(text="⚠ CAPS LOCK ON" if caps_on else "")

        if (event.state & 0x4) and event.keysym == "q":
            self.root.destroy()
            return

        if self.session.state == "READY":
            if event.keycode == 13:
                self.session.start()
                self.time_start = datetime.now()
                self.refresh_state()
            return

        if event.state & 0x4:
            if event.keysym == "BackSpace":
                self.user_input = " ".join(self.user_input.split()[:-1]) + " "
                self.draw_textbox()
            return

        if event.keycode == 13:
            self.submit()
        elif event.keycode == 27:
            self.session.abort()
            self.refresh_state()
        elif event.keycode == 8:
            self.user_input = self.user_input[:-1]
            self.user_input_full += event.char
            self.draw_textbox()
        else:
            if self.user_input == "":
                self.time_start = datetime.now()
            target_line = self.session.current_line()
            next_index = len(self.user_input)
            correct = next_index < len(target_line) and event.char == target_line[next_index]
            if self.session.settings.flash_on_mistake and event.char and not correct:
                self.flash_mistake()
            if self.session.settings.stop_on_error and event.char and not correct:
                # Stop-on-error: the wrong character is simply not accepted, so the
                # typist cannot run ahead of their own accuracy. Still recorded, or
                # the analysis would never see the mistakes this mode prevents.
                self._record_keystroke(event.char, correct)
                self.draw_textbox()
                return
            if event.char:
                self._record_keystroke(event.char, correct)
            self.user_input += event.char
            self.user_input_full += event.char
            self.draw_textbox()

    def _record_keystroke(self, char, correct):
        """One entry of the per-line keystroke record, ms from the first keypress."""
        ms = (datetime.now() - self.time_start).total_seconds() * 1000.0
        self.keystrokes.append({"char": char, "ms": round(ms, 1), "correct": bool(correct)})

    def submit(self):
        """Hand the line to the engine and show what it said."""
        elapsed = datetime.now() - self.time_start
        duration = round(elapsed.seconds + elapsed.microseconds / 1e6, 3)
        result = self.session.submit_line(
            self.user_input,
            duration,
            typed_full=self.user_input_full,
            when=self.time_start,
            keystrokes=self.keystrokes,
        )
        if result.passed:
            self.results_str = f"Wpm: {result.wpm:.0f}, Acc: {result.accuracy:.1%}"
        else:
            self.results_str = f"FAIL - Acc: {result.accuracy:.0%}, {result.wpm:.0f} wpm."
        self.user_input = ""
        self.user_input_full = ""
        self.keystrokes = []
        self.time_start = datetime.now()
        self.instructions["text"] = (
            f"Press Enter to finish or Esc to exit. Prev: {self.results_str}"
        )
        self.draw_textbox()
        self.update_position_label()

    # ---- drawing -----------------------------------------------------------

    def draw_textbox(self):
        """Current line with per-character colouring, then the upcoming lines in grey."""
        self.text_box.configure(state="normal")
        self.text_box.delete(1.0, "end")
        visible_lines = self.session.visible_lines(self.display_nlines)
        if not visible_lines:
            self.text_box.configure(state="disabled")
            return

        target_line = visible_lines[0]
        if len(self.user_input) <= len(target_line):
            display_first = self.user_input + target_line[len(self.user_input) :]
        else:
            display_first = self.user_input

        self.text_box.insert(1.0, "\n".join([display_first] + visible_lines[1:]))

        for index, typed_char in enumerate(self.user_input):
            target_char = target_line[index] if index < len(target_line) else None
            tag = "correct" if target_char is not None and typed_char == target_char else "incorrect"
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
        self.session.change_position(n)
        self.refresh_state()

    def update_position_label(self):
        self.textposition.config(
            text=f"{self.session.position}/{self.session.line_count} "
            f"({self.session.progress:.1%})"
        )

    def prompt_page_jump(self, event=None):
        if self.session.line_count <= 0:
            return
        selected_page = simpledialog.askinteger(
            "Go to page",
            f"Enter page number (1-{self.session.line_count}):",
            parent=self.root,
            minvalue=1,
            maxvalue=self.session.line_count,
        )
        if selected_page is None:
            return
        self.session.jump_to(selected_page)
        self.refresh_state()


def run():
    """Open the window. This is the whole desktop entry point."""
    root = tk.Tk()
    width, height = 1200, 500
    canvas = setup_window(
        root, screen_dims=(1920, 720), window_dims=(width, height), scaling=1.0
    )
    canvas.grid(columnspan=3, rowspan=3)
    Game(root, window_width=width, window_height=height)
    root.mainloop()
