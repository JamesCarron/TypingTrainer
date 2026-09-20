# UI refresh: research and proposals

Research into how the popular typing tools present typing and post-session analysis, and what TypingTrainer should take from each. Written 2026-09-19, after the refactor in `Refactor_Plan.md` put a served web UI in place. Nothing here is implemented — this is the brainstorm, and the decisions at the end are still open.

The brief that shapes it: Monkeytype is the design reference, and **post-session analysis that identifies typing weak points and helps fix them is a headline feature, not a decoration.**

## What the field does

Looked at in the browser on 2026-09-19, not from memory. TypeLit.io — the one product with the same premise, retyping whole books — would not render at all in Chrome, so it is absent from this comparison and worth another attempt later.

### Monkeytype — the aesthetic reference

A 30-second test, and the whole design follows from that: nothing on screen competes with the words.

- **No containers.** No card, no border, no panel. Flat background, text floating in space, generous emptiness below. Our current page puts the text in a bordered card, which is the single biggest visual difference between the two.
- **Measured typography.** Roboto Mono at 32px on a 40px line box, 1280px measure. Monospace is doing real work: the line does not reflow as you type, so nothing jitters.
- **Errors are the only colour.** Untyped text is dim grey, correctly typed text becomes the *normal* foreground, and only mistakes take a colour (a muted red, `#ca4754`). Correct characters are not green — brightness alone marks progress. Our page colours correct characters green, which on a 90-character line of prose is a lot of noise for information the user already has.
- **A five-token palette** drives the entire theme system: background, main (accent and caret), sub (dim), text, error. That is the same shape as the token set we already have, one level smaller.
- **A caret**, a blinking bar that slides between characters, is most of what makes it feel like a typing app rather than a diff viewer.
- **Chrome disappears while typing** and fades back afterwards. The config bar, header and footer are all present at rest and gone mid-test.
- **The results screen is the payoff**: a huge WPM and accuracy pair, a WPM/raw/error line chart over the duration of the test, then a quiet row of secondary stats — raw, characters as correct/incorrect/extra/missed, consistency, time.
- Everything is reachable from a command palette, and the keyboard hints sit at the bottom of the screen.

### keybr — the analysis reference

Where Monkeytype measures a test, keybr models the typist. This is the vocabulary to steal for the analysis work.

- The practice screen carries a **per-key skill strip** — every letter as a chip, the ones you have unlocked bright, the current target key boxed — plus "current key: not calibrated, need more samples", accuracy streaks and a daily-goal bar.
- An **on-screen keyboard coloured by finger**, with the next key highlighted and home-row markers.
- The profile page is the real product: all-time and today tiles (time, lessons, top and average speed, top and average accuracy); **accuracy streaks**; **relative speed and accuracy histograms** showing where you sit against everyone else; a **learning-progress overview** with one lane per key, red for slow and green for fast, across lesson number; a **typing-speed-over-time** chart with a smoothing slider; a **key typing speed histogram** (average speed per individual key); a **key frequency histogram** (hit count, miss count and miss ratio per key as three series); a **key frequency heatmap** drawn on a keyboard; and a **practice calendar** shaded by how much of the daily goal was met.
- It also offers **download your data** and **reset statistics** as first-class buttons, which is a good model for a local-first tool.

### TypeRacer — competition, and one idea worth taking

Skeuomorphic, gamified, cars. Nothing to take visually. The idea worth taking is that a race can be **replayed** afterwards and that each race keeps a per-keystroke log — watching your own typing played back, with the pauses intact, shows you things no aggregate can.

## What TypingTrainer is, and why it cannot just copy Monkeytype

The unit of work here is a **line of a book**, not a 30-second test, and the arc is 444 lines long. A Monkeytype-style results screen after every line would be unbearable: it fires 444 times. So the borrowing has to be split by cadence.

| Cadence | What belongs there |
|---|---|
| Per keystroke | live colouring, caret, error marking — Monkeytype's surface, exactly |
| Per line | a one-line verdict, no ceremony: WPM, accuracy, pass or fail |
| Per session | the Monkeytype results screen, moved here: charts, the stat row, what improved |
| All time | keybr's profile: per-key model, weak points, calendar, learning curve |

That table is the actual proposal. Everything below is detail under it.

## Proposal A — the typing surface

1. **Delete the card.** Flat background, no border, text floating. Keep one subtle surface only if the settings panel needs somewhere to sit.
2. **Monospace, 28–32px, line height around 1.6.** Higher than Monkeytype's 1.25 because these are long prose lines with descenders and punctuation, not short words. Measure capped near 70 characters so a book line does not run the full width of a monitor.
3. **Invert the colour convention**: untyped dim, correct normal, wrong in the error colour with an underline, and a wrong *space* as a filled error-coloured block so it is visible at all. Green disappears entirely.
4. **A real caret** — a bar that slides, with a blink that pauses while typing.
5. **Fade the chrome during GAME** and bring it back on Esc or on finishing a line.
6. **Show the previous line above, dimmed**, as well as the lines ahead. Prose needs backwards context in a way that word lists do not; you have just typed that sentence's first half.
7. **Live WPM and accuracy**, small and dim, top-left of the text block, and switchable off.
8. **Replace the full-screen ✗ flash.** Options, in increasing severity: colour the character only (Monkeytype's behaviour); a short shake of the current line; or a genuine *stop on error* mode where the wrong character will not be accepted at all. The third is the best training mechanic and the biggest behaviour change.

## Proposal B — the book

9. **Progress as a real object.** A chapter-aware bar with "line 346 of 444 · 78% · about 2 h left at your recent pace". The estimate is the motivating part, and we have the history to compute it honestly.
10. **A session summary** when you stop: lines completed, the WPM curve across the session, accuracy, time typing, best and worst lines. This is Monkeytype's results screen at the right cadence.
11. **The failure path should teach.** A failed line currently just repeats. Show the diff — what you typed against the target, with the error positions marked — before the retry.
12. **Streak and calendar**, keybr-style, driven by the daily-goal idea.

## Proposal C — post-session analysis

The headline. Split by what the data we already hold can support, versus what needs new instrumentation.

### Available now from the 208 stored attempts, with no new data

Each record already holds the target line, the submitted text, the *full* keystroke text including characters that were later deleted, the duration, accuracy and WPM. That is enough for:

- **A character confusion table.** Align target against submitted and count (intended, typed) pairs. "You type `r` when you mean `e` 14 times" is immediately actionable, and nothing in Monkeytype or keybr tells you this from real prose.
- **A per-character error rate**, drawn as a keyboard heatmap — keybr's picture, built from your own book rather than from generated drills.
- **Problem words.** Which actual words you get wrong most: proper nouns, long words, anything with a doubled letter.
- **A correction rate.** The full-keystroke text minus the submitted text is how much you typed and deleted — a decent proxy for hesitation, and it is already in every record.
- **Categories that matter for a book**: capitals, punctuation, quotes, digits, and apostrophes as separate error classes. A typist who is fine on letters and loses every attempt on semicolons should be told that.
- **Learning curves**: WPM and accuracy per line over 208 attempts, smoothed, plus how many attempts each line took.

### Needs one small change: record keystrokes

Storing a timestamped keystroke list per line — roughly 100 entries of `{char, ms, correct}` — unlocks the analysis that actually finds weak points:

- **Per-key latency**, and therefore a ranked list of your slowest keys.
- **Bigram latency**, which is where the real signal is. `th` is fast for everyone; your personal slow transitions are what cost you. A top-20 slowest-transitions list is the single most useful output on this page.
- **Same-finger bigrams, per-finger and per-hand breakdowns**, rolls versus alternations.
- **Rhythm**: the variance of inter-key intervals, and where in a line you stall for more than half a second.
- **Whether errors are preceded by a slowdown**, which distinguishes "does not know the key" from "going too fast".
- **Replay**, TypeRacer's idea: play a line back at the speed you typed it.

The cost is one field on the attempt record, a list from the browser on `POST /api/attempt`, and the same list captured in the desktop key handler. Old records simply lack the field, so nothing breaks.

### Turning analysis into improvement

Diagnosis without a next action is just a chart. Each of these closes the loop:

- **Drill lines generated from your own weaknesses** — synthesise practice lines from your top confusions and slowest bigrams, the way keybr generates lessons from its key model, but from *your* error history.
- **"Find me a hard line"** — pick the line from the book ahead of you that is densest in your weak characters, and make it the next one.
- **A warm-up** before a session: three drill lines aimed at the current worst keys.
- **Criteria that adapt** — nudge the minimum WPM up as the rolling average rises, instead of leaving it at whatever was set months ago.
- **A watchlist** of trouble words, reviewable and clearable.

### Where the code goes

The analysis is pure functions over history records, so it belongs in the engine (`src/typingtrainer/analysis.py`), exposed through `GET /api/analysis` and rendered by both front ends. No analysis logic in JavaScript — the parity rule already says so, and here there is no live-rendering excuse for it.

One storage decision falls out: JSON history is fine at 208 records and fine at 2,000, but keystroke lists at 10,000 lines is tens of megabytes read and rewritten on every attempt. SQLite is the obvious answer if keystroke capture goes ahead.

## What the real data turned out to look like

Measured against a copy of the real store on 2026-09-19, once the stats page could render it. Two things that change what to build next.

**The weak-point analysis is starved, and not because the code is wrong.** Across 209 attempts and 20,566 lowercase characters there are eight mistyped characters in total. The reason is the criteria: with a 99% accuracy floor, a line is retyped until it is right, so the *submitted* text is almost always perfect and the mistakes never reach the store. Error categories still ranked quotes worst (5% of 20 seen) and punctuation next (0.4% of 934), which is a genuine finding, but it rests on single-digit counts. The signal is not missing — it is in the keystrokes, which now record every character pressed including the ones deleted and the ones stop-on-error refused. The fix is to derive the confusion pairs from the keystroke stream rather than from the final submitted text.

That needed one more field, and it is now in: each keystroke records what was *expected* as well as what was pressed. The expected character cannot be reconstructed afterwards — backspaces are deliberately not recorded, so the position at any given press is ambiguous — so it is captured at press time in both front ends, added to the `keystrokes` table through an additive column migration, and read by `analysis.keystroke_confusions` and `analysis.keystroke_character_errors`. The stats page prefers those over the submitted-text versions wherever they have data and says which it is showing; `drills.weak_targets` prefers them too, falling back for history recorded before the field existed.

Verified end to end on 2026-09-19 by typing a line with a deliberate mistake, correcting it, and submitting a perfect line: the submitted-text view reported no confusions at all, while the keystroke view caught `G → X` and rated `G` at a 50% error rate. That is the difference between the analysis working for this user and not.

**One corrupt legacy record was distorting every aggregate.** An attempt stored 1236 wpm with an empty `user_input`, an accuracy of 0.0 and a suspiciously round 1.0 s duration — internally inconsistent, from a code path that no longer exists. It was setting the all-time top-speed tile and flattening the learning curve against its axis. `analysis._implausible` now excludes records above 300 wpm or with a non-positive duration from the aggregates and counts them; the row stays in the store, because nothing here rewrites history. Real top speed is 95.32 wpm, mean 67.44.

## What was built, 2026-09-20

The design rounds settled on **Wings v2 with deep analysis as a moment**, and it is implemented. The mockups that got there are in `docs/mockups/`: `UI_Mockups.html` (five directions), `UI_Mockups_Hybrid.html` (three ways to combine Zen, Coach and Cockpit), `UI_Mockup_Wings.html` (Wings with rails, and the reserve-versus-drawer question) and `UI_Mockup_Wings_v2.html` (the agreed base plus the three homes for the deep analysis). They are working prototypes rather than pictures, because every decision in this sequence was about timing or interaction and neither can be judged from a still.

**The shape that was chosen.** Permanent slim rails down both edges, always present including while typing, every figure labelled (`WPM`, `ACC`, `WORST`, `STEP`, `LINE`) after bare numerals proved ambiguous in an earlier round. The right rail updates live as you type, throttled to about six recomputations a second, in fixed-width tabular slots so the frame cannot shudder as digits change. Clicking a rail expands it into a drawer that overlays the line and dims the centre; the line keeps its full measure, which is itself a setting (`measure_ch`, 50 to 86 characters, default 78). The deep analysis has no door on the rail at all: it is the closing act of a session, a review screen of what moved since last time with one recommended next action, and "See everything" is the only route to `/stats`.

**The grace period never shipped.** It existed in the prototypes so the pause behaviour could be felt, and it was the right idea while the rails appeared and disappeared. Once the rails became permanent and the figures live, it had nothing left to govern, and it was never added to the app.

**Three defects were found by driving the real thing**, none of which the test suite would have caught:

- Pressing Enter and typing immediately lost every character until `POST /api/start` returned, because the key handler waited for the round trip before leaving the READY branch. The page now enters GAME optimistically and reverts if the request fails.
- Pressing Enter on an empty buffer logged a 0% failed attempt. That drags the mean accuracy down and writes a record with an empty `user_input` — precisely the shape of the corrupt legacy row that `analysis._implausible` already has to exclude, so the store had been accumulating them. Both front ends now refuse an empty submit.
- The review named "lower" as the worst error category at 0.0%, because within one session every category ties at zero and the tie-break fell back to alphabetical order. It now requires an actual error before naming a category, and says nothing when the session was clean.

## Decisions (2026-09-19)

All four settled at the end of the research session. They are ambitious on purpose: the whole set was chosen, not a subset.

1. **The typing surface gets the full Monkeytype treatment, plus stop-on-error.** Card gone, inverted colour convention, sliding caret, dimmed previous line, live WPM, chrome fading during GAME — and a mode where a wrong character is not accepted at all, so you cannot outrun your own accuracy. Stop-on-error is a setting, defaulting off, because it changes how the app feels and the existing criteria already enforce accuracy at line level.
2. **Keystrokes are recorded from now on, and history moves to SQLite in the same change.** Doing both at once avoids migrating twice. This goes first, before any UI work, so data accumulates while the rest is being built.
3. **All four analysis groups are wanted**: weak-point diagnosis, speed diagnosis, progress over time, and the improvement loop. Weak-point and progress work on the 208 existing records immediately; speed diagnosis only starts producing results once keystroke data accumulates, which is the second reason instrumentation goes first.
4. **Session summary first, deeper page behind it.** Stopping a session shows the results screen; a link on it opens the full analysis at its own route. The typing screen itself stays empty, which is the entire point of the surface work.

## Build order

Same wave structure as the refactor: serial where judgement is needed, parallel where the file sets are disjoint, a green suite at every gate.

- **Wave 1 — the data layer** (serial). SQLite store behind the existing `history` API, keystroke capture through `Session.submit_line`, `stop_on_error` added to settings, JSON and pickle both migrating in, tests rewritten. Nothing else can start until the record shape is fixed.
- **Wave 2 — analysis engine and typing surface** (parallel, disjoint). `analysis.py` with the weak-point, speed and progress functions over the store; separately the page rewrite in `templates/` and `static/`.
- **Wave 3 — the results screen and the stats route** (parallel, disjoint). Session summary plus `/stats`; separately `drills.py` for the improvement loop.
- **Wave 4 — wiring** (serial, small). Drills into the UI, adaptive criteria, and the documents updated.
