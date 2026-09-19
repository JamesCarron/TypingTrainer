# TypingTrainer Refactor Plan

Staged plan to bring `C:\GitHub\TypingTrainer` into line with the house layout in `C:\Auterion\Tools\Project_Folder_Structure.md`, and to add a served web UI alongside the existing tkinter app. Written 2026-09-19. Plan only at this point — no stage below has been applied.

## Goal

Three things at once, in an order where each is verifiable on its own:

1. **Layout.** Apply the house standard: `src/<pkg>/` installed editable, `tests/` at root, `scripts/` thin, `docs/` for every document, one `paths.py` resolving state and output roots through `platformdirs`, pixi for the environment, a launcher `.bat`, no user data in the checkout.
2. **Architecture.** Pull the typing engine out of the 786-line `Game` class so it is UI-agnostic, then run two front ends on it — the existing tkinter desktop app and a new served web UI.
3. **Web app.** The same shape as the other tools: a local Python server on an ephemeral port, real `templates/page.html` + `static/page.css` + `static/page.js`, launched by a `.bat`, browser opened at the printed URL.

## Decisions taken up front (2026-09-19)

Asked and answered before the plan was written. Recorded here so the next session does not re-litigate them.

- **The repo stays at `C:\GitHub\TypingTrainer`.** It is a personal public GitHub project, not an Auterion tool, and moving it under `C:\Auterion\Tools` would put it inside the Google Drive sync. The house standard is applied in place, as a layout convention rather than because the folder is in scope.
- **Data roots carry no `Auterion` vendor folder**, following from the above: state at `%LOCALAPPDATA%\TypingTrainer\`, cache at `%LOCALAPPDATA%\TypingTrainer\Cache\`, user texts and exports at `~\Documents\TypingTrainer\`, all overridable together by `TYPINGTRAINER_HOME`.
- **Both front ends are kept, on one shared core.** The tkinter app is not frozen or deleted; it becomes a thin view over the extracted engine, so it keeps working offline with no server. The cost is accepted knowingly: every new feature has to land in two views, and the engine is what stops that becoming two implementations.
- **JS renders, Python scores.** The browser captures keystrokes and paints the per-character diff live — a round trip per keystroke is not viable — but the moment a line is submitted, Python is authoritative for accuracy, WPM, pass/fail and persistence. The duplicated character comparison is covered by a parity test: the JS diff must equal `compare_lines()` over a fixture corpus.
- **`SaveGame.pickleddict` migrates to JSON and leaves the working tree.** A one-off `pixi run migrate` reads the pickle, writes history and per-text positions as JSON into the state dir, reports what it moved, and the file is then `git rm`ed. The pickle stays in past commits; git history is not being rewritten.

## Current state

```
TypingTrainer/
  main.py                 17 lines: builds the tk root, constructs Game, mainloop
  TypingTrainer.py        786 lines: class Game — widgets, key handling, scoring, config, history, persistence
  functions.py            266 lines: setup_window (tkinter), compare_lines, typing_score, str_find_all, subdivide_line, run_tests
  Texts.py                52 lines: class Text — load a .txt, clean and wrap it, track position
  config.json             six settings, written beside the code
  SaveGame.pickleddict    113 KB pickle: per-text position + full attempt history, committed
  Texts/artofwar.txt      the one bundled corpus
  Images/                 icon, logo, mascot (used by the tk window)
  Resources/              four deprecated standalone experiments + PDFextract_text-main, an unrelated vendored tutorial
  run.bat                 activates .venv, runs main.py
  .idea/  .vscode/  __pycache__/   all three tracked in git
```

Audit against the standard (`refactor-project\audit.py`, 2026-09-19): git present and tree clean; no `src/` layout and no `paths.py`; **0 tests**; no `scripts/`, no `docs/`; no pixi, no `pyproject.toml`, no `platformdirs`; one filename with a space (`Resources\speed typing.py`); no `user_data/` and no credential-looking files. Seven `.pyc` files and the whole `.idea/` folder are tracked. Every path in the code is `getcwd()`-relative, so the app only runs with the repo root as the working directory.

## Target layout

```
TypingTrainer/
  TypingTrainer.bat            launcher: default web UI, --desktop for tkinter
  README.md  CLAUDE.md         what it is and how to run it; agent conventions
  pixi.toml  pixi.lock         tasks: ui, desktop, test, where, migrate
  pyproject.toml               package name, src layout, pytest importlib mode
  .gitignore  .gitattributes
  src/typingtrainer/
    __init__.py
    paths.py                   state / cache / documents roots, TYPINGTRAINER_HOME override, display() helper
    scoring.py                 compare_lines, typing_score, passing_grade — pure, no UI, no clock
    linebreak.py               subdivide_line, str_find_all — pure text wrapping
    texts.py                   Text (load, clean, wrap, position) + library discovery over bundled and user texts
    config.py                  Settings dataclass, load/save JSON in the state dir
    history.py                 attempt records and per-text positions, JSON in the state dir
    session.py                 the headless game: state machine, submit_line, advance, results — no tkinter, no HTTP
    migrate.py                 one-off pickle + repo config.json -> state dir JSON
    texts_bundled/artofwar.txt the sample corpus that ships with the repo
    desktop/app.py             tkinter view over Session (was Game's widget half)
    desktop/window.py          setup_window (was in functions.py)
    web/server.py              http.server on an ephemeral port, JSON API, native path picker
    templates/page.html
    static/page.css  page.js
    static/img/                mascot and icon, referenced by the page
  scripts/                     serve.py, where.py, migrate.py — argument parsing only, one call each
  tests/                       pytest; tests/js/ for the parity fixtures
  docs/                        this plan, and every document written during the work
  (outside the repo)
  %LOCALAPPDATA%\TypingTrainer\            settings.json, history.json, positions.json
  %LOCALAPPDATA%\TypingTrainer\Cache\      nothing yet; reserved
  ~\Documents\TypingTrainer\Texts\         the user's own .txt corpora, changeable in the UI
```

## Stages

Each stage is one commit, with the test suite run before and after. A failing suite reverts that stage (`git checkout -- . && git clean -fd`) and stops the run. Stages 0 to 2 exist so that from stage 3 onward there is actually something to run.

### Stage 0 — hygiene

Untrack what should never have been committed and fix the filename rule. No behaviour changes.

- `git rm -r --cached __pycache__ .idea` and extend `.gitignore` to `/__pycache__/`, `.idea/`, `.venv/`, `.pixi/`, `*.pyc`, `.pytest_cache/`.
- `git mv "Resources/speed typing.py" Resources/speed_typing.py`.
- Add `.gitattributes` marking `pixi.lock` `linguist-generated -diff` (the existing file only sets line endings).
- Move `Resources/` to `docs/legacy_experiments/` — four standalone scripts nothing imports — and decide `Resources/PDFextract_text-main/` separately (see Open questions).
- Write a real `README.md`: what the trainer is, how to run both front ends, and a "Where your data lives" section.

Verify: `python main.py` still starts the tkinter app from the repo root.

### Stage 1 — environment

- `pixi.toml`: python `>=3.12,<3.15`, `pillow` (the tk view's mascot), `platformdirs`; feature `dev` with `pytest`. Tasks `desktop`, `test`, `where` now; `ui` and `migrate` land with their stages.
- `pyproject.toml`: package `typingtrainer`, src layout, `[tool.pytest.ini_options] addopts = ["--import-mode=importlib"]`.
- Editable install line: `[pypi-dependencies] typingtrainer = { path = ".", editable = true }`.
- `run.bat` becomes `TypingTrainer.bat`, written with `newline=""` so cmd.exe keeps its CRLFs.

Verify: `pixi install` succeeds; `pixi run desktop` starts the app.

### Stage 2 — smoke tests, before anything moves

The audit reports zero tests, and the failures the later stages cause are silent ones — a wrapper that wraps differently, a corpus that loads as an empty list — not crashes. This suite is what makes stages 3 to 7 verifiable.

- `tests/test_scoring.py` — golden cases for `compare_lines` (equal, shorter guess, longer guess, empty) and `typing_score` (accuracy and WPM to the rounding the current code produces), pinned to the current outputs.
- `tests/test_linebreak.py` — `subdivide_line` at both split types, including the limit-boundary and no-punctuation cases.
- `tests/test_corpus_snapshot.py` — load `artofwar.txt` through `Text.clean_file` and assert the line count and the first and last three lines against a committed snapshot. This is the test that catches a path change silently loading nothing.
- `functions.run_tests()` is folded into these and deleted.

Verify: `pixi run test` green. Commit the snapshot with it.

### Stage 3 — package move and engine extraction

The largest stage. Move by `git mv` where a file maps one to one, and split `TypingTrainer.py` by hand.

- `functions.py` splits: `compare_lines` / `typing_score` to `scoring.py`, `str_find_all` / `subdivide_line` to `linebreak.py`, `setup_window` to `desktop/window.py`.
- `Texts.py` to `texts.py`; `texts_dir` stops being `getcwd()`-derived and comes from `paths` plus the bundled folder.
- `Game` splits into `session.Session` (state machine `READY`/`GAME`, current text, `submit_line(typed, duration)` returning a result record, `advance`, `jump_to`, criteria evaluation) and `desktop/app.py` (every widget, `draw_textbox`, `flash_mistake`, the key bindings, the settings dialogs). Nothing in `session.py` may import tkinter; that is the check that the split is real.
- `passing_grade` moves to `scoring.py` as a pure function of `(results, settings)`.
- The clock leaves the engine: `submit_line` takes a duration, it does not call `datetime.now()`. That is what makes the web path and the tests able to drive it.
- `tests/test_session.py` covers the state machine and pass/fail against the criteria, headless.

Verify: `pixi run test` green, and `pixi run desktop` actually played through two lines by hand. The suite passing is not sufficient here — the standard's own notes record a green suite over a moved module writing to the wrong place.

### Stage 4 — paths and data migration

- `src/typingtrainer/paths.py` from the new-project template with the placeholders filled: `state_dir()`, `cache_dir()`, `documents_dir()`, `texts_dir()`, each `mkdir(parents=True, exist_ok=True)` on first use; `TYPINGTRAINER_HOME` overrides state and cache together; a `display()` helper that labels a path by its root and never raises (a `relative_to(REPO)` in a log line breaks the moment a path resolves into `%LOCALAPPDATA%`).
- `config.py` reads and writes `state_dir()/settings.json`, keeping the existing six keys and their defaults.
- `history.py` writes `state_dir()/history.json` (attempt records keyed by ISO timestamp) and `state_dir()/positions.json` (per-text line position).
- `migrate.py` + `pixi run migrate`: load `SaveGame.pickleddict` and the repo `config.json`, write the three JSON files, print counts on both sides, and only then report the originals as removable. Move-by-rename semantics do not apply here — this is a format conversion, so verify record counts rather than bytes.
- `scripts/where.py` and `pixi run where` print every resolved path.
- `git rm SaveGame.pickleddict config.json`; add both patterns to `.gitignore` so a stray copy cannot be re-committed.
- `tests/test_paths.py` points `TYPINGTRAINER_HOME` at a tmp dir and asserts every root lands under it; `tests/test_migrate.py` runs the converter over a small synthetic pickle.

Verify: `pixi run migrate` on the real save file, then `pixi run desktop` resumes at the same line with history intact.

### Stage 5 — web server and API

- `web/server.py`: `http.server.ThreadingHTTPServer` bound to `("127.0.0.1", 0)`, port read back and the URL printed on stdout; `scripts/serve.py` parses `--no-browser` and calls it; `pixi run ui`; `TypingTrainer.bat` launches it and opens the printed URL.
- The page is assembled from real files — `templates/page.html` with `{{CSS}}` and `{{JS}}` placeholders filled from `static/` per request. No HTML, CSS or JS in a Python string, ever.
- JSON API, one `Session` per server process:
  - `GET /api/state` — current text, position, visible lines, settings, last result
  - `GET /api/texts` and `POST /api/text` — the library, and selecting one
  - `POST /api/attempt` `{typed, duration_ms}` — the authoritative scoring call; returns matches, accuracy, WPM, pass/fail, new position
  - `GET|POST /api/settings` — the six criteria
  - `POST /api/position` — previous, next, jump to line
  - `POST /api/history/reset` — current text or all
  - `POST /api/pick_path` — native `tkinter.filedialog` picker in a subprocess behind a lock, for the Browse button on the texts folder
- `tests/test_server.py` drives the API end to end over a real ephemeral-port server.

Verify: the page serves, and a full line typed in the browser advances the position and survives a reload.

### Stage 6 — web front end and parity

Feature parity with the tk app is the acceptance bar, item by item: live per-character colouring of the current line, upcoming lines greyed, flash on mistake, caps-lock warning (`event.getModifierState("CapsLock")`), Enter to submit, Esc to abort the line, Ctrl+Backspace to delete the last word, previous/next/jump controls, the position label, the criteria display and the settings panel, reset history.

- `static/page.js` holds keystroke capture, the live diff and the rendering; everything else calls the API.
- **Parity test** `tests/js/test_diff_parity.py`: a fixture corpus of (target, typed) pairs, the JS `diff()` run under node, asserted equal to `scoring.compare_lines` for every pair. The fixture file is shared by `tests/test_scoring.py`, so one corpus covers both implementations.
- Styling: house tokens rather than raw hex — see Open questions on which stylesheet a personal public repo should carry.

Verify: opened in Chrome from a served URL, screenshotted, every control read at desktop width, in both themes.

### Stage 7 — text library

- Bundled `artofwar.txt` stays in the package as the sample; the user's own corpora live in `~\Documents\TypingTrainer\Texts\`, listed alongside it with the source shown.
- Both front ends get an add-a-text path: Browse in the web UI (native picker via `/api/pick_path`), the existing file dialog on the desktop. Files are copied into the library folder, never read from wherever they happened to be — a text is re-read every session, so an in-place reference to a Downloads folder breaks quietly.
- `tests/test_texts_library.py` covers discovery across both sources and the name-collision case.

### Stage 8 — documents

- `CLAUDE.md` at root: the two-front-ends rule, where logic may and may not live, how to run the tests, and the parity requirement.
- `README.md` finished with the Layout block and "Where your data lives".
- This plan updated in place with what actually happened per stage.

## Parallelising the work

The stages above are written as a serial chain because that is how they are verified, but the dependency graph is not a chain. Stage 3 (the engine extraction) is the trunk: it is the only stage that rewrites existing code wholesale, everything downstream of it needs a headless `Session`, and it must not be split across agents. Everything else is either upstream of it or writes new files it does not touch.

Three waves, with the critical path running straight down the middle:

**Wave A — before stage 3, three streams in parallel.** None of them touch `TypingTrainer.py`, so they cannot collide.

- *Hygiene and environment* (stages 0 and 1): untracking, the filename rename, `.gitignore`, `.gitattributes`, `pixi.toml`, `pyproject.toml`, `README.md`, the launcher. Touches only config and root files.
- *Golden tests* (stage 2): `tests/test_scoring.py`, `tests/test_linebreak.py`, `tests/test_corpus_snapshot.py` and the committed snapshot, written against the current flat modules and re-pointed at the package in one line each after stage 3. All new files.
- *Paths and migration* (stage 4's new code): `paths.py`, `migrate.py`, `scripts/where.py`, `tests/test_paths.py`, `tests/test_migrate.py`. All new files; the wiring of `config.py` and `history.py` into them waits for stage 3 because those modules do not exist yet.

**Wave B — stage 3 alone.** One agent, no parallelism, because every file it produces is a judgement call about where a line of the old `Game` belongs and a second agent working the same class would be resolving merge conflicts rather than writing code. Gate: `pixi run test` green on the wave A suites, and the desktop app played through two lines by hand.

Before wave B ends it must publish the two contracts wave C builds against, and they are the thing that makes wave C parallel at all: the `Session` public API (method names, argument types, the shape of the result record) and the JSON API endpoint list from stage 5. Write both into this document as the last act of wave B.

**Wave C — after stage 3, three streams in parallel.**

- *Web server and API* (stage 5): `web/server.py`, `scripts/serve.py`, `tests/test_server.py`, the `ui` pixi task, the launcher change.
- *Web front end* (stage 6): `templates/page.html`, `static/page.css`, `static/page.js`, the parity fixture and `tests/js/test_diff_parity.py`. Builds against the published endpoint list, so it can start before the server is finished; the two meet at the browser check, which is serial and belongs to whoever finishes second.
- *Desktop re-wire and text library* (stage 7 plus the tk view's share of stage 3): `desktop/app.py` finished against the real `Session`, `texts.py` library discovery, `tests/test_texts_library.py`.

Stage 8 (documents) is serial and last, because it records what the other stages actually did.

Practicalities, because parallel agents on one repo go wrong in predictable ways:

- **One git worktree per stream**, not three agents in one checkout. Each commits in its own worktree and the branches merge at the wave gate. Three agents sharing a working tree will fight over `pixi.toml` and the index.
- **A wave gate is a real gate.** Merge all of a wave's branches, run the full suite once on the merged tree, and only then start the next wave. A suite that was green on each branch separately is not evidence about the merge.
- **`pixi.toml` is the one file every stream wants.** It belongs to the hygiene-and-environment stream in wave A and to nobody in wave C; a wave C stream that needs a new dependency or task asks for it rather than editing it.
- **What this actually buys.** The whole codebase is 1,452 lines. Wave A is perhaps an hour of work split three ways, wave B is the bulk of the job and cannot be split, and wave C is genuinely three-way. Expect the parallelism to help most in wave C and to be close to overhead-neutral in wave A.

## Risks, and what they cost

- **The engine split is the whole job.** If `session.py` ends up importing tkinter or reaching for `datetime.now()`, the web front end will need a second copy of the game logic and the refactor has failed in its main purpose. A test that `session.py` imports with tkinter absent is worth writing.
- **Two front ends is the standing cost of the decision taken above.** Stages 5 to 7 should not add anything the desktop app cannot also be given, or the two views drift and the engine stops being the single source.
- **The scoring parity test only holds if both sides read one fixture file.** Two fixture lists is the same bug as two implementations.
- **`Path.read_text` normalises CRLF**, which corrupts a `.bat` on rewrite; use `newline=""` in stage 1.
- **A corpus that silently loads empty** is the specific failure the stage 2 snapshot exists to catch, and the reason stage 2 comes before any move.

## How to continue

Apply the stages in order with `/refactor-project C:\GitHub\TypingTrainer`, or run them by hand: test, apply one stage, test, commit with the stage name. Stages 0 to 4 are the layout migration and stand on their own — the repo is in a coherent, standards-compliant state after stage 4 even if the web work never happens. Stages 5 to 7 are the web app and depend on stage 3 having produced a genuinely headless `Session`.

## Open questions

Put to the user at the end of the planning session; answers get recorded here.

1. `Resources/PDFextract_text-main/` is an unrelated vendored tutorial (a Flask PDF-extraction demo) with its own README. Delete it, or move it out of the repo?
2. The four scripts in `Resources/` are superseded experiments. Keep them as `docs/legacy_experiments/`, or delete them and let git history hold them?
3. Which stylesheet does a personal public GitHub repo use? The house rule points every generated page at `C:\Auterion\Tools\brand`, which is Auterion brand material and would not belong in a public personal project.
4. No `LICENSE` file and the repo is public. Naming the gap only — the choice is yours.
