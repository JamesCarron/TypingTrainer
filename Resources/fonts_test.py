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

    shortlist = [
        "Copperplate Gothic Bold",
        "Gill Sans MT",
        "Georgia",
        "Sitka Small",
        "System",
        "Courier New",
        "Eras Light ITC",
        "Papyrus",
        "Eras Medium ITC",
        "Copperplate Gothic Light",
        "HGPKyokashotai",
        "Roboto Slab",
        "HGMaruGothicMPRO",
        "Courier",
    ]


def shortlist_font(self):
    self.font_shortlist += [self.fonts[self.font_index]]
    self.font_shortlist = list(set(self.font_shortlist))
    print("Font Shortlist:")
    [print(f"{i}:{font}") for i, font in enumerate(self.font_shortlist)]


# STYLING EXPERIMENTATION
import tkinter.font as tkFont

self.font_index = 0
self.fonts = list(tkFont.families())
self.change_font(self.title, 0, 60)  # set to start
self.font_shortlist = list()
# prev font button
browse_text = tk.StringVar()
font_btn = tk.Button(
    root,
    textvariable=browse_text,
    command=lambda: self.change_font(self.title, -1),
    font=button_style,
    bg=acc_primary_c,
    fg=acc_primary_fc,
    height=1,
    width=10,
)
browse_text.set("PrevFont")
font_btn.grid(column=0, row=5)

# font shortlist button
browse_text = tk.StringVar()
font_btn = tk.Button(
    root,
    textvariable=browse_text,
    command=lambda: self.shortlist_font(),
    font=button_style,
    bg=acc_primary_c,
    fg=acc_primary_fc,
    height=1,
    width=10,
)
browse_text.set("AddFontToShortlist")
font_btn.grid(column=1, row=5)

# next font button
browse_text = tk.StringVar()
font_btn = tk.Button(
    root,
    textvariable=browse_text,
    command=lambda: self.change_font(self.title, 1, 60),
    font=button_style,
    bg=acc_primary_c,
    fg=acc_primary_fc,
    height=1,
    width=10,
)
browse_text.set("NextFont")
font_btn.grid(column=2, row=5)

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
