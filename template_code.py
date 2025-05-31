# Reset button
browse_text = tk.StringVar()
brows_btn = tk.Button(root, textvariable=browse_text, command=lambda: load_text(), font='Raleway', bg='#20bebe',
                      fg='white', height=2, width=15)
browse_text.set("Next for Text")
brows_btn.grid(column=1, row=2)

# Add space at the end of the GUI
canvas = tk.Canvas(root, width=width, height=300)
canvas.grid(columnspan=3)

# Center text
box.tag_configure('center', justify='center')
box.tag_add('center', 1.0, 'end')