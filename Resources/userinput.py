def draw_userinput(self):
    self.userinput_box.configure(state="normal")
    self.userinput_box.delete(1.0, "end")  # clear
    self.userinput_box.insert(1.0, f"{self.user_input}")  # new user input
    self.userinput_box.configure(state="disabled")


# user input
self.userinput_box = tk.Text(
    root,
    height=4,
    width=int(self.width * 0.055),
    padx=5,
    pady=5,
    font=text_style,
)
self.userinput_box.grid(column=0, row=2, columnspan=3)
self.userinput_box.config(wrap="word")
self.draw_userinput()
