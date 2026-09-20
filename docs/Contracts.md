# Contracts

The two interfaces that let the front ends be built independently of each other: the `Session` API that both views drive, and the JSON API the web view speaks to the server. Written 2026-09-19 during the refactor described in `Refactor_Plan.md`. Anything that changes here changes two front ends at once, so change it deliberately.

## Session — `src/typingtrainer/session.py`

The headless game. No tkinter, no HTTP, no `print`, and no clock: `submit_line` is handed the duration rather than measuring it, which is what makes both the browser path and the tests able to drive it. One `Session` is one player working through one text; the desktop app owns one, and the server owns one per process.

```python
@dataclass(frozen=True)
class AttemptResult:
    target: str          # the line that was being typed
    typed: str           # what the user actually submitted
    matches: list[bool]  # per-character, length of the longer of the two
    accuracy: float      # 0.0 to 1.0, rounded as scoring.typing_score rounds it
    wpm: float
    duration: float      # seconds, as given
    passed: bool         # against the current settings
    position: int        # the line position AFTER the attempt (advanced only on a pass)
```

| Member | Contract |
|---|---|
| `Session(settings=None, store=None, text=None)` | All three default to the real ones: settings from `config.load()`, store from `history`, text from the last-used or the bundled sample. Tests pass their own. |
| `state` | `"READY"` or `"GAME"`. No other value is valid; setting an invalid one raises `ValueError`, as the original did. |
| `text_name`, `position`, `line_count`, `progress` | Read-only view of where the player is. `position` is 0-based internally; `progress` is `position / line_count`. |
| `current_line()` | The line to be typed now. Returns `""` past the end of the text rather than raising. |
| `visible_lines(n=5)` | The current line plus the next `n-1`, for the display. Short list at the end of a text. |
| `start()` | `READY` to `GAME`. Clears the typed buffer. |
| `abort()` | `GAME` to `READY`. Discards the attempt without logging it — matches the current Esc behaviour. |
| `submit_line(typed, duration)` | The whole scoring path: score, log to history, advance on a pass, persist position and history. Returns `AttemptResult`. Legal only in `GAME`; raises otherwise. |
| `change_position(delta)` | Move by lines, clamped to `[0, line_count]`. Sets `READY`. Persists. |
| `jump_to(line_number)` | 1-based, as the user sees it. Clamped. Sets `READY`. Persists. |
| `available_texts()` | `{display name: Path}` over the bundled sample and the user's `Documents\TypingTrainer\Texts\`. |
| `select_text(name)` | Switch text, restoring that text's saved position. Sets `READY`. |
| `add_text(source_path)` | Copy a `.txt` into the user's library and return its display name. Never reads it in place afterwards. |
| `update_settings(**kwargs)` | Partial update of the six settings, validated and saved. Returns the new `Settings`. |
| `reset_history(scope)` | `"current"` or `"all"`. Returns the number of records removed. |
| `snapshot()` | Everything a view needs in one dict: state, text name, position, line count, progress, visible lines, settings, and the last `AttemptResult` if there is one. The web layer serialises this straight out of `GET /api/state`. |

## JSON API — `src/typingtrainer/web/server.py`

One process, one `Session`, bound to `127.0.0.1` on an ephemeral port. Every response is JSON except `GET /`. Errors are `{"error": "<message>"}` with a 4xx status; the page shows the message rather than failing silently.

| Method and path | Body | Returns |
|---|---|---|
| `GET /` | — | the assembled page: `templates/page.html` with `{{CSS}}` and `{{JS}}` filled from `static/` |
| `GET /api/state` | — | `Session.snapshot()` |
| `GET /api/texts` | — | `{"texts": [{"name": ..., "source": "bundled"\|"library"}], "current": name}` |
| `POST /api/text` | `{"name": ...}` | the new snapshot |
| `POST /api/start` | — | the new snapshot |
| `POST /api/abort` | — | the new snapshot |
| `POST /api/attempt` | `{"typed", "duration_ms", "typed_full"?, "keystrokes"?}` | `{"result": AttemptResult, "state": snapshot}` — **the authoritative score**; the browser's live diff is display only |
| `POST /api/position` | `{"delta": n}` or `{"line": n}` | the new snapshot |
| `GET /api/settings` | — | the six settings |
| `POST /api/settings` | any subset of the six | the new settings |
| `POST /api/history/reset` | `{"scope": "current"\|"all"}` | `{"removed": n}` |
| `POST /api/text/add` | `{"path": ...}` | the new text's name and the new snapshot |
| `GET /api/users` | — | `{"users": [{"name", "anonymous", "attempts", "last_active", "line"}], "current": name}`, most recently active first |
| `POST /api/user` | `{"name": ...}` or `{"anonymous": true}` | the snapshot for that user; creates them if new, mints `Guest N` when anonymous |
| `POST /api/user/rename` | `{"from": ..., "to": ...}` | the snapshot under the new name; 400 if the target exists |
| `POST /api/pick_path` | `{"kind": "file"\|"dir"}` | `{"path": ...}` or `{"path": null}` if cancelled — native picker in a subprocess behind a lock |

Rules that go with it:

- **The browser never computes a score that is kept.** It computes the live per-character diff for colouring, and that is all. Accuracy, WPM and pass/fail come back from `POST /api/attempt`, and the page renders what the server said even if its own diff disagreed.
- **The live diff must agree with `scoring.compare_lines` anyway**, and `tests/js/test_diff_parity.py` proves it over `tests/fixtures/diff_corpus.json`. One fixture file, both implementations; two fixture lists would be the same bug as two implementations.
- **Keystrokes are sent with the attempt, not streamed.** `keystrokes` is a list of `{"char", "ms", "correct"}` in press order, `ms` measured from the first keypress of the line, covering every character key pressed — including characters later deleted, and including ones stop-on-error refused. Backspaces are not entries. The field is optional and malformed lists are rejected rather than coerced, because a wrong number in a latency statistic is worse than no number. Added 2026-09-19; see `docs/UI_Refresh_Notes.md`.
- **Users are a choice of name, not authentication.** There are no passwords and nothing is protected; the point is separate progress on a shared machine. A browser with no remembered name is given a `Guest N` automatically and can put a real name on that progress later through the rename, which carries every attempt and the reading position across. Renaming onto an existing name is refused rather than merged: two histories joined by accident cannot be separated again. Added 2026-09-20.
- **No state in the page that the server does not also hold.** A reload re-reads `GET /api/state` and lands exactly where the player was.
