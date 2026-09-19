# TypingTrainer

A typing trainer that works through a real book, line by line. You type the current line, it scores you on accuracy and words per minute, and it only advances when the attempt meets the criteria you set. Your position and your full attempt history are remembered between sessions.

Two front ends, one engine: a served web UI (the default) and the original tkinter desktop app.

## Running it

```
TypingTrainer.bat              the web UI: starts a local server and opens the browser
TypingTrainer.bat --desktop    the tkinter desktop app
```

Both are also pixi tasks:

```
pixi run ui          serve the web UI on an ephemeral port
pixi run desktop     the tkinter app
pixi run test        the full test suite
pixi run where       print every path the tool reads or writes
pixi run migrate     one-off: import an old SaveGame.pickleddict into the new store
```

There is no install step. `pixi run` builds the environment on first use, and every data folder is created the first time it is needed.

## Where your data lives

Nothing the tool writes is kept inside the repo.

| What | Where |
|---|---|
| Settings, attempt history, per-text position | `%LOCALAPPDATA%\TypingTrainer\` |
| Downloaded or derived caches | `%LOCALAPPDATA%\TypingTrainer\Cache\` |
| Your own texts to type | `~\Documents\TypingTrainer\Texts\` |

Set `TYPINGTRAINER_HOME` to move the state and cache roots together. `pixi run where` prints whatever the resolution came to.

The tool makes no network calls. The web UI is a local server bound to `127.0.0.1` on a port the OS picks, and nothing you type leaves the machine.

## Layout

```
TypingTrainer.bat            launcher
src/typingtrainer/           the package; all logic lives here
  paths.py                   the only module that knows where data goes
  scoring.py  linebreak.py   pure functions: character diff, accuracy, WPM, line wrapping
  texts.py  config.py  history.py
  session.py                 the headless game; no tkinter, no HTTP
  desktop/                   the tkinter view
  web/  templates/  static/  the server and the page it assembles
scripts/                     thin entry points: serve.py, where.py, migrate.py
tests/                       pytest
docs/                        design documents and task summaries
```
