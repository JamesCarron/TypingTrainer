"""The Text class: load a .txt corpus, clean and wrap it, track reading position.

Extracted verbatim (same behaviour) from the pre-refactor root-level `Texts.py`.
`load()` keeps its existing signature, `load(self, texts_dir)` -- the caller
still supplies the directory; this stage does not wire it up to `paths.py`.

Written 2026-09-19 for the "Golden tests" stream of Wave A of the TypingTrainer
refactor (see docs/Refactor_Plan.md). Verified by tests/test_texts.py.
"""

from re import sub
from os import path

from typingtrainer.linebreak import subdivide_line


class Text:
    def __init__(self, text_name, location):
        self.lines = 0
        self.name = text_name
        self.loc = location
        self.loaded = False
        self.contents = None  # text itself. Each line is ready to be displayed
        self.position = 0  # what line number the user has reached
        self.line_len_limit = 100

    def clean_file(self, file, line_len_limit=100, split_type="LHS"):
        """
        Take a raw text file and process it so its ready for use in the game
        Steps:
        Remove newline chars and spaces from the start and end of file
        Replace any repeated spaces with a single space.
        Ensure each line is not longer then X chars long so it can be properly displayed.
        :cvar
        """
        new_contents = list()
        for line in file:
            if line in ["", "\n"]:
                continue  # ignore empty lines
            new_contents += subdivide_line(line.strip(), line_len_limit, split_type)

        # Fixed 2026-09-19: both of these used to throw their result away --
        # the loop rebound a local and never wrote back -- so the collapse this
        # docstring promises never happened. On the bundled Art of War it makes
        # no difference (444 lines before and after, no line changed), because
        # that text has no doubled internal spaces; it matters for a text the
        # user adds.
        return [
            sub(r"[\s]{2,}", " ", line.strip()) for line in new_contents
        ]

    def load(self, texts_dir):
        with open(path.join(texts_dir, self.loc)) as file:
            self.contents = file.readlines()
        self.contents = self.clean_file(
            self.contents, line_len_limit=200, split_type="LHS"
        )
        self.loaded = True
        self.lines = len(self.contents)

    def __len__(self):
        return self.lines  # initialised to zero if file not loaded

    def get_current_line(self):
        return self.contents[self.position]
