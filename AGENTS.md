# AGENTS.md

Conventions for working in this repo. (Named `CLAUDE.md` until 2026-09-19; renamed because this repo is public and the conventions are not tool-specific.) The README says what the tool is and how to run it; this file says only what an agent needs that the README does not cover.

## The one rule this repo exists to keep

**Two front ends, one engine.** `src/typingtrainer/session.py` is the whole game — state machine, scoring path, history, position, settings — and it imports no GUI toolkit, opens no socket, prints nothing and never reads the clock. `desktop/app.py` and `web/` are views over it. A feature added to one view and not the other is a bug; logic added to a view rather than to the engine is a worse one, because it is how the two implementations start.

`tests/test_session.py::test_session_module_does_not_import_tkinter` fails if that is undone. It is not a style check.

## Where things go

| Kind of change | Where |
|---|---|
| Game rules, scoring, persistence, text handling | `src/typingtrainer/` — never in a view |
| A widget, a dialog, a key binding | `src/typingtrainer/desktop/app.py` |
| A control, layout or live rendering in the browser | `src/typingtrainer/templates/page.html`, `static/page.css`, `static/page.js` |
| An endpoint | `src/typingtrainer/web/server.py`, and `docs/Contracts.md` in the same commit |
| A filesystem location | `src/typingtrainer/paths.py`, and nowhere else. No other module may name a directory |
| A document of any kind | `docs/`. Root holds `README.md` and this file only |

## Testing

```
pixi run test          everything
pixi run where         print the resolved data paths
```

Every test runs against a temporary state root: set `TYPINGTRAINER_HOME` **and** monkeypatch `platformdirs.user_documents_dir`, because the documents root is deliberately not covered by the environment override. Copy the `isolated` fixture from `tests/test_session.py`. A test that writes into the real `%LOCALAPPDATA%\TypingTrainer\` or `~\Documents\TypingTrainer\` is a defect even if it passes — that folder holds the user's real typing history.

A green suite is not sufficient evidence for a change that moves code between folders. Run the real entry points as well (`pixi run desktop`, `pixi run ui`); the failure mode this repo's refactor kept hitting was a suite happily testing an artefact that the moved code was no longer writing.

## The browser's diff is display only

`static/page.js` computes a per-character diff so it can colour the line as it is typed. That number never becomes a score: `POST /api/attempt` returns the authoritative accuracy, WPM and pass/fail, and the page renders what came back. `tests/js/test_diff_parity.py` runs the page's own JS under node against `tests/fixtures/diff_corpus.json` and asserts it agrees with `scoring.compare_lines`. One fixture file feeds both; a second list would be the same defect as a second implementation.

## Three old bugs, fixed 2026-09-19

All three were found during the refactor, pinned by tests, deliberately left alone for a while, and then fixed on request. The tests now pin the fixed behaviour, so do not "restore" any of them:

- `typing_score` used to raise `ZeroDivisionError` on an empty target line. An empty guess against an empty target now scores 1.0, anything typed against it scores 0.0, and a zero duration yields 0 WPM instead of dividing by zero.
- `Text.clean_file` called `sub()` and threw the result away, so the whitespace collapse its docstring promised never happened. It now returns the collapsed lines. This is a no-op on the bundled Art of War — 444 lines before and after, no line changed — and only matters for a text the user adds.
- `passing_grade`'s "accuracy above 100%" guard sat inside the `require_accuracy` branch, so an impossible score sailed through whenever that criterion was off. It is a check on the scorer, not on the criterion, and now runs either way.

Migrated history records from before the refactor still carry a literal unformatted `EventTime` string and no `Length` key. They are passed through unchanged; do not normalise them without being asked. One record holds an impossible 1236 WPM with an empty input — `analysis._implausible` keeps it out of the aggregates rather than deleting it.

## Styling

This repo does not use any house or corporate stylesheet — it is public and personal. Semantic CSS variables on `:root`, light and dark, no raw hex anywhere else, system fonts, no CDN, no web fonts, no JS libraries. Desktop width is the only target.

## Privacy

The tool makes no network calls. The server binds `127.0.0.1` on an ephemeral port. Nothing the user types leaves the machine, and nothing the tool writes goes inside the repo.
