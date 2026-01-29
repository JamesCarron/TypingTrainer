from functions import subdivide_line
from re import sub
from os import path


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

        for line in new_contents:
            line = line.strip()  # remove any white space at the start or end of a line
            sub(
                r"[\s]{2,}", " ", line
            )  # replace any occurrence of two or more spaces with a single space.

        return new_contents

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
