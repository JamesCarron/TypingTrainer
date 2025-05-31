from tkinter.filedialog import askopenfile
from os import getcwd

def get_sentence(file_location, line):
    sentences = open(file_location).readlines()
    sentence = sentences[line].strip()
    return sentence

def load_text():
    global root
    """
    Allows the user to add a text to the trainer.
    :return:
    """
    browse_text.set('Loading...')
    file = askopenfile(parent=root, initialdir=getcwd(), title="Choose a file", filetype=[("Text file", '*.txt')])
    if file != None:
        print("File was loaded successfully")
        text = [line.strip() for line in file.readlines()]

        #text box
        text_box = tk.Text(root, height=10, width=50, padx=15, pady=15)
        text_box.insert(1.0, f"{nl.join(text)}")
        text_box.tag_configure('center', justify='center')
        text_box.tag_add('center', 1.0, 'end')
        text_box.grid(column=1, row=3)
        browse_text.set('Loaded')
    else:
        print("Something went wrong")
        browse_text.set('Browse')