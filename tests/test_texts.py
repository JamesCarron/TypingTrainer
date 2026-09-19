"""Golden test for typingtrainer.texts.Text against the bundled artofwar.txt corpus.

Loads src/typingtrainer/texts_bundled/artofwar.txt through Text and asserts the line
count and the first and last three lines against tests/fixtures/artofwar_snapshot.json.
This is a tripwire: a later stage that silently loads nothing, points at the wrong
directory, or wraps lines differently (e.g. a line_len_limit or split_type change)
will fail this test even though nothing raises.

To regenerate the snapshot after a *deliberate* change to the bundled text or the
wrapping behaviour, run from C:\\GitHub\\TypingTrainer:

    pixi run python -c "
    import json
    from typingtrainer.texts import Text
    t = Text('artofwar', 'artofwar.txt')
    t.load('src/typingtrainer/texts_bundled')
    snapshot = {
        'line_count': len(t.contents),
        'first_three': t.contents[:3],
        'last_three': t.contents[-3:],
    }
    json.dump(snapshot, open('tests/fixtures/artofwar_snapshot.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    "
"""

import json
from pathlib import Path

from typingtrainer.texts import Text

REPO_ROOT = Path(__file__).parent.parent
TEXTS_BUNDLED_DIR = REPO_ROOT / "src" / "typingtrainer" / "texts_bundled"
SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "artofwar_snapshot.json"


def test_artofwar_matches_snapshot():
    text = Text("artofwar", "artofwar.txt")
    text.load(str(TEXTS_BUNDLED_DIR))

    with open(SNAPSHOT_PATH, encoding="utf-8") as f:
        snapshot = json.load(f)

    assert len(text.contents) == snapshot["line_count"]
    assert text.contents[:3] == snapshot["first_three"]
    assert text.contents[-3:] == snapshot["last_three"]
    assert len(text) == snapshot["line_count"]
