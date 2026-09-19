"""Thin shim re-exporting the Text class from the typingtrainer package.

Pre-refactor, this module held the Text class body directly. As of the "Golden
tests" stream of Wave A (see docs/Refactor_Plan.md), the logic lives in
src/typingtrainer/texts.py, covered by tests/test_texts.py. TypingTrainer.py keeps
importing `from Texts import Text` unchanged.
"""

from typingtrainer.texts import Text

__all__ = ["Text"]
