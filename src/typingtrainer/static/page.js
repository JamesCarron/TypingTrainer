/*
 * page.js -- the web front end's whole client: keystroke capture, the live
 * per-character diff (for colouring only -- the server is authoritative for
 * scoring, see docs/Contracts.md), and every control that drives the JSON API.
 *
 * Written 2026-09-19 for stage 6 of the TypingTrainer refactor
 * (docs/Refactor_Plan.md), against the API published in docs/Contracts.md.
 * Rewritten 2026-09-19 for the Monkeytype-style typing surface
 * (docs/UI_Refresh_Notes.md, Proposal A): a real caret, chrome that fades
 * while typing, a dimmed previous line, live WPM/accuracy, and stop-on-error.
 *
 * Rewritten again 2026-09-20 for "Wings v2"
 * (docs/mockups/UI_Mockup_Wings_v2.html):
 *   - permanent left/right rails that expand in place into drawers (a panel
 *     overlays the line, the line keeps its full measure)
 *   - the right rail's WPM/ACC recompute live while typing, throttled to a
 *     150ms interval rather than per keystroke, with the grace period
 *     removed entirely
 *   - the line's width comes from the `measure_ch` setting, applied as
 *     --measure on the stage
 *   - deep analysis is a moment: finishing a session opens a full-stage
 *     review (GET /api/review, every field optional) whose only door out is
 *     "See everything" to /stats
 *
 * `diff()` below must have exactly the semantics of
 * `typingtrainer.scoring.compare_lines`: itertools.zip_longest(guess, answer,
 * fillvalue=False), so the result is as long as the LONGER string. It is
 * exported for tests/js/test_diff_parity.py to run under node, unmodified --
 * the parity test loads this file itself rather than a pasted copy.
 */

/**
 * Character-by-character comparison, matching
 * typingtrainer.scoring.compare_lines exactly: the result is padded to the
 * length of the longer string, and a padding slot never equals anything
 * (mirrors zip_longest's fillvalue=False, which can never equal a real
 * character).
 *
 * @param {string} guess
 * @param {string} answer
 * @returns {boolean[]}
 */
function diff(guess, answer) {
  // Python iterates by Unicode codepoint (len() on a str counts codepoints,
  // not UTF-16 code units), so a naive guess[i]/answer[i] would double-count
  // any character outside the BMP (e.g. an emoji) as two surrogate halves.
  // Array.from splits on codepoints, matching Python's str iteration.
  const guessChars = Array.from(guess);
  const answerChars = Array.from(answer);
  const length = Math.max(guessChars.length, answerChars.length);
  const matches = new Array(length);
  for (let i = 0; i < length; i++) {
    const g = i < guessChars.length ? guessChars[i] : false;
    const a = i < answerChars.length ? answerChars[i] : false;
    matches[i] = g === a;
  }
  return matches;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { diff };
}

// The rest of this file is browser-only: it never runs under node, since the
// parity test only imports `diff` via module.exports above.
if (typeof window !== "undefined") {
  (function () {
    "use strict";

    const API = {
      async get(path) {
        const res = await fetch(path);
        return handle(res);
      },
      async post(path, body) {
        const res = await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body || {}),
        });
        return handle(res);
      },
    };

    async function handle(res) {
      let data;
      try {
        data = await res.json();
      } catch (err) {
        throw new Error(`bad response (${res.status})`);
      }
      if (!res.ok) {
        throw new Error(data && data.error ? data.error : `request failed (${res.status})`);
      }
      return data;
    }

    // ---- state --------------------------------------------------------------

    let snapshot = null; // last GET /api/state (or equivalent) response
    let typed = ""; // what the player has typed on the current line, minus deletions

    // Per-keystroke instrumentation (docs/UI_Refresh_Notes.md, Proposal C):
    // every character key pressed, in press order, including ones later
    // deleted and ones rejected by stop-on-error. Backspaces are never
    // recorded here and never remove an entry. `lineStart` is the timing
    // baseline for both this list's `ms` field and the submitted
    // `duration_ms` -- mirrors desktop/app.py's single `time_start`, reset
    // whenever the buffer empties out so idle "thinking" time before typing
    // (or re-typing after backspacing everything) is not counted.
    let keystrokes = [];
    let lineStart = null;

    let isTyping = false; // true from the first keystroke of the current line
    let idleTimer = null; // clears the caret's "solid while typing" state
    let railTimer = null; // throttles the right rail's live recompute (~6/s)
    let flashTimer = null; // clears a transient char-flash / shake

    let lastPosition = null; // for showing the previous line, best-effort
    let lastTargetLine = null;
    let previousLineText = null;
    let flashIndex = null; // index in the current line to show a char-flash

    // The right rail freezes on the finished line's server-returned values
    // the instant a line is submitted, and holds them until the very next
    // keystroke -- it never shows a number the server did not say.
    let heldRailValues = null; // {wpm, accuracy, passed} | null

    // The last submitted attempt's keystrokes, kept only to compute the
    // display-only "stalls" figure in the right drawer -- never resent,
    // never scored again.
    let lastAttemptKeystrokes = [];

    let drawerOpen = null; // "left" | "right" | null
    let reviewOpen = false;

    const els = {};

    function $(id) {
      return document.getElementById(id);
    }

    document.addEventListener("DOMContentLoaded", init);

    async function init() {
      els.stage = $("stage");
      els.wingLeft = $("wing-left");
      els.wingRight = $("wing-right");
      els.centre = $("centre");
      els.typingArea = $("typing-area");
      els.currentLine = $("current-line");
      els.previousLine = $("previous-line");
      els.upcomingLines = $("upcoming-lines");
      els.caret = $("caret");
      els.capslock = $("capslock-warning");
      els.instructions = $("instructions");
      els.errorBar = $("error-bar");

      // Left rail / drawer.
      els.railStep = $("rail-step");
      els.railTicks = $("rail-ticks");
      els.railLine = $("rail-line");
      els.railTotal = $("rail-total");
      els.panelTextName = $("panel-text-name");
      els.panelPosition = $("panel-position");
      els.panelLastResult = $("panel-last-result");
      els.textPicker = $("text-picker");
      els.addTextBtn = $("add-text-btn");
      els.prevBtn = $("prev-btn");
      els.nextBtn = $("next-btn");
      els.measureInput = $("measure-input");
      els.measureVal = $("measure-val");
      els.resetHistoryBtn = $("reset-history-btn");
      els.finishSessionBtn = $("finish-session-btn");

      // Right rail / drawer.
      els.railWpm = $("rail-wpm");
      els.railAcc = $("rail-acc");
      els.railWorst = $("rail-worst");
      els.detailWpm = $("detail-wpm");
      els.detailAcc = $("detail-acc");
      els.detailVerdict = $("detail-verdict");
      els.detailCriteriaLabel = $("detail-criteria-label");
      els.detailStalls = $("detail-stalls");
      els.keystrip = $("keystrip");

      // Review.
      els.review = $("review");
      els.reviewSession = $("review-session");
      els.reviewWpm = $("review-wpm");
      els.reviewAccuracyLine = $("review-accuracy-line");
      els.reviewMoved = $("review-moved");
      els.reviewRecommendation = $("review-recommendation");
      els.reviewStartBtn = $("review-start-btn");
      els.reviewBackBtn = $("review-back-btn");

      buildKeystrip();

      els.prevBtn.addEventListener("click", () => movePosition(-1));
      els.nextBtn.addEventListener("click", () => movePosition(1));
      els.panelPosition.addEventListener("click", promptJump);
      els.textPicker.addEventListener("change", onTextPicked);
      els.addTextBtn.addEventListener("click", onAddText);
      els.resetHistoryBtn.addEventListener("click", onResetHistory);
      els.finishSessionBtn.addEventListener("click", openReview);
      els.reviewStartBtn.addEventListener("click", startNextFromReview);
      els.reviewBackBtn.addEventListener("click", closeReview);

      for (const wing of [els.wingLeft, els.wingRight]) {
        wing.addEventListener("click", (event) => {
          if (event.target.closest("input, select, button, a, label")) return;
          const side = wing.dataset.wing;
          if (drawerOpen === side) closeDrawer();
          else openDrawer(side);
        });
      }

      els.centre.addEventListener("click", () => {
        if (reviewOpen) return;
        if (drawerOpen) closeDrawer();
        focusTypingArea();
      });

      for (const input of document.querySelectorAll("[data-setting]")) {
        input.addEventListener("change", onSettingChanged);
      }
      // Live preview while dragging the line-width slider -- purely visual
      // until "change" fires and persists it like any other setting.
      els.measureInput.addEventListener("input", () => {
        applyMeasure(els.measureInput.value);
      });

      window.addEventListener("resize", positionCaret);

      document.addEventListener("keydown", onKeyDown);
      document.addEventListener("click", (event) => {
        // Clicking anywhere that is not an interactive control returns focus
        // to the typing area -- the typing area must never lose keyboard
        // focus for a stray click.
        if (!event.target.closest("button, input, label, select, a")) {
          focusTypingArea();
        }
      });

      await Promise.all([refreshState(), refreshTexts()]);
      refreshWorstKeys();
      focusTypingArea();
    }

    function focusTypingArea() {
      els.typingArea.focus();
    }

    function showError(message) {
      if (!els.errorBar) return;
      els.errorBar.textContent = message;
      els.errorBar.hidden = false;
    }

    function clearError() {
      if (!els.errorBar) return;
      els.errorBar.hidden = true;
      els.errorBar.textContent = "";
    }

    function setTyping(value) {
      isTyping = value;
      if (value) {
        startRailTicker();
      } else {
        stopRailTicker();
      }
    }

    // ---- drawers --------------------------------------------------------------

    function openDrawer(side) {
      els.stage.classList.remove("open-left", "open-right");
      els.stage.classList.add(side === "left" ? "open-left" : "open-right");
      drawerOpen = side;
    }

    function closeDrawer() {
      els.stage.classList.remove("open-left", "open-right");
      drawerOpen = null;
    }

    // ---- rendering ------------------------------------------------------------

    function currentTarget() {
      return (snapshot && snapshot.visible_lines && snapshot.visible_lines[0]) || "";
    }

    function applyMeasure(chValue) {
      const n = parseInt(chValue, 10);
      const clamped = Number.isFinite(n) ? Math.min(86, Math.max(50, n)) : 78;
      els.stage.style.setProperty("--measure", clamped + "ch");
      els.measureInput.value = String(clamped);
      els.measureVal.textContent = String(clamped);
    }

    function render() {
      if (!snapshot) return;

      // Best-effort "previous line": only known when this snapshot is one
      // line further on than the last one we rendered (the normal forward
      // flow of typing through the book). A jump, a text switch or a manual
      // reposition simply has no previous line to show -- Session does not
      // expose one, and this view may not invent state the engine does not
      // also hold (docs/Contracts.md: "no state in the page the server does
      // not also hold" -- this is display-only best effort, never submitted).
      const target = currentTarget();
      if (lastPosition !== null) {
        if (snapshot.position === lastPosition + 1) {
          previousLineText = lastTargetLine;
        } else if (snapshot.position !== lastPosition) {
          previousLineText = null;
        }
      }
      lastPosition = snapshot.position;
      lastTargetLine = target;

      renderLeftRail();
      renderPreviousLine();
      renderLines();
      renderInstructions();
      renderSettingsForm();
      updateLiveRail();
    }

    function renderLeftRail() {
      const pct = snapshot.line_count ? (snapshot.progress * 100) : 0;
      els.railStep.textContent = `${pct.toFixed(0)}%`;
      els.railLine.textContent = String(snapshot.position);
      els.railTotal.textContent = String(snapshot.line_count);

      els.railTicks.innerHTML = "";
      const totalTicks = 10;
      const filled = Math.min(totalTicks, Math.floor((snapshot.progress || 0) * totalTicks));
      for (let i = 0; i < totalTicks; i++) {
        const tick = document.createElement("i");
        if (i < filled) tick.className = "done";
        else if (i === filled) tick.className = "now";
        els.railTicks.appendChild(tick);
      }

      els.panelTextName.textContent = `"${snapshot.text_name}"`;
      els.panelPosition.textContent =
        `line ${snapshot.position}/${snapshot.line_count} (${pct.toFixed(1)}%) — click to jump`;

      const last = snapshot.last_result;
      if (last) {
        els.panelLastResult.textContent = last.passed
          ? `Prev: ${last.wpm.toFixed(0)} wpm, ${(last.accuracy * 100).toFixed(1)}% acc`
          : `Prev: FAIL — ${(last.accuracy * 100).toFixed(0)}% acc, ${last.wpm.toFixed(0)} wpm`;
      } else {
        els.panelLastResult.textContent = "";
      }
    }

    function renderPreviousLine() {
      els.previousLine.textContent = previousLineText || "";
    }

    function renderLines() {
      const visible = (snapshot && snapshot.visible_lines) || [];
      const target = visible[0] || "";

      els.currentLine.innerHTML = "";
      const matches = diff(typed, target);
      const length = Math.max(typed.length, target.length);
      for (let i = 0; i < length; i++) {
        const span = document.createElement("span");
        const hasTyped = i < typed.length;
        const typedChar = hasTyped ? typed[i] : target[i];
        span.textContent = typedChar;
        if (hasTyped) {
          span.className = matches[i] ? "char-correct" : "char-incorrect";
          const targetChar = i < target.length ? target[i] : null;
          if (!matches[i] && (typed[i] === " " || targetChar === " ")) {
            span.classList.add("char-incorrect-space");
          }
        } else {
          span.className = "char-pending";
        }
        if (flashIndex !== null && i === flashIndex) {
          span.classList.add("char-flash");
        }
        els.currentLine.appendChild(span);
      }

      els.upcomingLines.innerHTML = "";
      for (const line of visible.slice(1)) {
        const div = document.createElement("div");
        div.className = "upcoming-line";
        div.textContent = line;
        els.upcomingLines.appendChild(div);
      }

      positionCaret();
    }

    function positionCaret() {
      if (!els.caret) return;
      const spans = els.currentLine.children;
      let left = 0;
      let top = 0;
      let height = parseFloat(getComputedStyle(els.currentLine).lineHeight) || 28;
      const idx = typed.length;
      if (spans.length === 0) {
        left = 0;
        top = 0;
      } else if (idx < spans.length) {
        const span = spans[idx];
        left = span.offsetLeft;
        top = span.offsetTop;
        height = span.offsetHeight;
      } else {
        const span = spans[spans.length - 1];
        left = span.offsetLeft + span.offsetWidth;
        top = span.offsetTop;
        height = span.offsetHeight;
      }
      els.caret.style.transform = `translate(${left}px, ${top}px)`;
      els.caret.style.height = `${height}px`;
      els.caret.classList.toggle("hidden-caret", !snapshot || snapshot.state !== "GAME");
    }

    function markCaretSolid() {
      if (!els.caret) return;
      els.caret.classList.add("solid");
      if (idleTimer) window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => {
        els.caret.classList.remove("solid");
      }, 500);
    }

    function renderInstructions() {
      const last = snapshot.last_result;
      let resultText = "";
      if (last) {
        resultText = last.passed
          ? ` Prev: Wpm: ${last.wpm.toFixed(0)}, Acc: ${(last.accuracy * 100).toFixed(1)}%`
          : ` Prev: FAIL - Acc: ${(last.accuracy * 100).toFixed(0)}%, ${last.wpm.toFixed(0)} wpm.`;
      }
      if (snapshot.state === "READY") {
        els.instructions.textContent = "Press Enter to start." + resultText;
      } else {
        els.instructions.textContent = "Press Enter to finish or Esc to exit." + resultText;
      }
    }

    function renderSettingsForm() {
      const s = snapshot.settings;
      for (const input of document.querySelectorAll("[data-setting]")) {
        const key = input.dataset.setting;
        if (key === "measure_ch") continue; // handled separately below
        if (!(key in s)) continue;
        if (input.type === "checkbox") {
          input.checked = !!s[key];
        } else if (input.type === "number") {
          if (key === "min_accuracy") {
            input.value = (s[key] * 100).toString();
          } else {
            input.value = s[key].toString();
          }
        }
      }
      // measure_ch may not exist yet on an older settings payload -- default
      // to the prototype's 78 so the page still works while it lands.
      const measure = s.measure_ch != null ? s.measure_ch : 78;
      applyMeasure(measure);
    }

    // ---- live rail: WPM / ACC recompute while typing, throttled ------------
    //
    // Rule that does not bend: this is display only. Nothing here is ever
    // sent anywhere; the authoritative score always comes back from
    // POST /api/attempt, and heldRailValues (below) is exactly that
    // server-returned value, just held on screen until the next keystroke.

    function updateLiveRail() {
      const s = snapshot && snapshot.settings;
      if (!s || !s.live_stats) {
        setRailFigures(null, null);
        return;
      }
      if (heldRailValues) {
        setRailFigures(heldRailValues.wpm, heldRailValues.accuracy, heldRailValues.passed);
        return;
      }
      if (!isTyping || !lineStart || typed.length === 0) {
        setRailFigures(null, null);
        return;
      }
      const target = currentTarget();
      const matches = diff(typed, target);
      const correct = matches.slice(0, typed.length).filter(Boolean).length;
      const elapsedMinutes = Math.max(Date.now() - lineStart, 1) / 60000;
      const wpm = (typed.length / 5) / elapsedMinutes;
      const accuracy = correct / typed.length;
      setRailFigures(wpm, accuracy);
    }

    // Fixed-width, tabular-numeral slots (see page.css .rf .v) so the rail
    // never shudders as the digit count changes underneath it.
    function setRailFigures(wpm, accuracy, passed) {
      if (wpm == null || accuracy == null) {
        els.railWpm.textContent = "—";
        els.railWpm.className = "v dash";
        els.railAcc.textContent = "—";
        els.railAcc.className = "v sm dash";
        return;
      }
      els.railWpm.textContent = wpm.toFixed(0);
      els.railAcc.textContent = (accuracy * 100).toFixed(0) + "%";
      if (passed === undefined) {
        els.railWpm.className = "v";
        els.railAcc.className = "v sm";
      } else {
        els.railWpm.className = "v" + (passed ? " good" : "");
        els.railAcc.className = "v sm" + (passed ? " good" : " bad");
      }
    }

    function startRailTicker() {
      stopRailTicker();
      updateLiveRail();
      // ~6.7 updates/sec: smooth without being a per-keystroke reflow.
      railTimer = window.setInterval(updateLiveRail, 150);
    }

    function stopRailTicker() {
      if (railTimer) {
        window.clearInterval(railTimer);
        railTimer = null;
      }
    }

    // ---- worst keys (right rail squares + drawer keyboard) -----------------
    //
    // Sourced from GET /api/analysis (already implemented server-side; this
    // page only reads it), specifically weak_points.keystroke_character_errors,
    // which counts every keystroke against what was expected -- including
    // corrected mistakes -- rather than only what survived into a submitted
    // line. Refreshed at load and after every submitted attempt, since it
    // only changes when history does.

    const KEYBOARD_ROWS = ["qwertyuiop", "asdfghjkl;", "zxcvbnm,.'"];
    let worstChars = []; // top few {char, error_rate}, most severe first

    function buildKeystrip() {
      els.keystrip.innerHTML = "";
      for (const row of KEYBOARD_ROWS) {
        for (const ch of row) {
          const i = document.createElement("i");
          i.textContent = ch;
          i.dataset.char = ch;
          els.keystrip.appendChild(i);
        }
      }
    }

    function heatClass(rank) {
      return rank === 0 ? "h3" : rank === 1 ? "h2" : "h1";
    }

    async function refreshWorstKeys() {
      try {
        const report = await API.get("/api/analysis");
        const rows =
          (report &&
            report.weak_points &&
            report.weak_points.keystroke_character_errors &&
            report.weak_points.keystroke_character_errors.characters) ||
          [];
        worstChars = rows.filter((r) => r.error_rate > 0).slice(0, 3);
      } catch (err) {
        worstChars = [];
      }
      renderWorstKeys();
    }

    function renderWorstKeys() {
      els.railWorst.innerHTML = "";
      worstChars.forEach((row, i) => {
        const el = document.createElement("i");
        el.className = heatClass(i);
        el.textContent = row.char;
        els.railWorst.appendChild(el);
      });

      const byChar = new Map(worstChars.map((row, i) => [row.char, heatClass(i)]));
      for (const el of els.keystrip.children) {
        const cls = byChar.get(el.dataset.char);
        el.className = cls || "";
      }
    }

    async function refreshState() {
      snapshot = await API.get("/api/state");
      clearError();
      render();
    }

    async function refreshTexts() {
      const data = await API.get("/api/texts");
      els.textPicker.innerHTML = "";
      for (const t of data.texts) {
        const option = document.createElement("option");
        option.value = t.name;
        option.textContent = `${t.name} (${t.source})`;
        if (t.name === data.current) option.selected = true;
        els.textPicker.appendChild(option);
      }
    }

    // ---- keyboard handling ------------------------------------------------

    // `expected` is what the typist should have pressed at this position. It is
    // recorded at press time because it cannot be reconstructed later:
    // backspaces are deliberately not part of the record, so the position at
    // any given press is ambiguous. It is also the only place a mistake
    // survives on a line that gets corrected before being submitted.
    function recordKeystroke(char, correct, expected) {
      const ms = lineStart ? Date.now() - lineStart : 0;
      keystrokes.push({
        char: char,
        expected: expected === undefined ? null : expected,
        ms: ms,
        correct: !!correct,
      });
    }

    function flashOffending(index) {
      flashIndex = index;
      if (flashTimer) window.clearTimeout(flashTimer);
      flashTimer = window.setTimeout(() => {
        flashIndex = null;
        renderLines();
      }, 220);
    }

    function shakeLine() {
      els.currentLine.classList.remove("shake");
      // Force reflow so the animation restarts on repeated mistakes.
      void els.currentLine.offsetWidth;
      els.currentLine.classList.add("shake");
    }

    function onKeyDown(event) {
      const capsOn = event.getModifierState && event.getModifierState("CapsLock");
      els.capslock.hidden = !capsOn;

      // Do not steal ordinary keystrokes typed into a settings field or the
      // jump prompt -- but Escape always falls through, so it can close a
      // drawer or the review even while a field has focus.
      if (event.key !== "Escape" && event.target !== els.typingArea && event.target.tagName !== "BODY") {
        if (event.target.matches && event.target.matches("input, select, textarea")) {
          return;
        }
      }

      if (!snapshot) return;

      if (event.key === "Escape") {
        event.preventDefault();
        // Esc climbs down one level at a time: the review, then a drawer,
        // then whatever Esc already did (abort the line, or open the review
        // from READY).
        if (reviewOpen) {
          closeReview();
          return;
        }
        if (drawerOpen) {
          closeDrawer();
          focusTypingArea();
          return;
        }
        if (snapshot.state === "READY") {
          openReview();
          return;
        }
        abortLine();
        return;
      }

      if (reviewOpen) return;

      if (snapshot.state === "READY") {
        if (event.key === "Enter") {
          event.preventDefault();
          startLine();
        }
        return;
      }

      // GAME state.
      if (event.ctrlKey && event.key === "Backspace") {
        event.preventDefault();
        typed = typed.replace(/\s+$/, "");
        const idx = typed.lastIndexOf(" ");
        typed = idx === -1 ? "" : typed.slice(0, idx + 1);
        renderLines();
        return;
      }

      if (event.key === "Enter") {
        event.preventDefault();
        submitLine();
        return;
      }
      if (event.key === "Backspace") {
        event.preventDefault();
        typed = typed.slice(0, -1);
        renderLines();
        return;
      }
      if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) {
        event.preventDefault();

        if (typed === "") {
          lineStart = Date.now();
        }
        // The instant typing resumes, the rail drops whatever it was
        // holding (a finished line's figures, or dashes) and starts
        // recomputing live.
        heldRailValues = null;
        if (!isTyping) {
          setTyping(true);
        }
        markCaretSolid();

        const target = currentTarget();
        const nextIndex = typed.length;
        const expected = nextIndex < target.length ? target[nextIndex] : null;
        const correct = expected !== null && event.key === expected;

        if (snapshot.settings.flash_on_mistake && !correct) {
          shakeLine();
        }

        if (snapshot.settings.stop_on_error && !correct) {
          // Stop-on-error: the wrong character is not accepted into the
          // buffer at all -- the caret does not advance -- but it is still
          // recorded and sent, or the analysis would never see the mistakes
          // this mode prevents (docs/UI_Refresh_Notes.md decision 1).
          recordKeystroke(event.key, correct, expected);
          flashOffending(nextIndex);
          return;
        }

        recordKeystroke(event.key, correct, expected);
        typed += event.key;
        renderLines();
      }
    }

    // ---- actions -----------------------------------------------------------

    function resetLineBuffers() {
      typed = "";
      keystrokes = [];
      lineStart = null;
      flashIndex = null;
      heldRailValues = null;
      setTyping(false);
      updateLiveRail();
    }

    async function startLine() {
      // Go to GAME locally before the round trip, not after it. A typist who
      // presses Enter and starts typing immediately -- which is most of them --
      // would otherwise have every character until the response lands dropped
      // on the floor by the READY branch of the key handler. The request is
      // still authoritative: if it fails we put the state back and say so.
      const previous = snapshot;
      snapshot = Object.assign({}, snapshot, { state: "GAME" });
      resetLineBuffers();
      render();
      focusTypingArea();
      try {
        const confirmed = await API.post("/api/start");
        // Keep whatever the typist has already entered; only the server's view
        // of the session replaces ours.
        snapshot = confirmed;
        clearError();
        render();
      } catch (err) {
        snapshot = previous;
        typed = "";
        keystrokes = [];
        render();
        showError(err.message);
      }
    }

    async function abortLine() {
      try {
        snapshot = await API.post("/api/abort");
        clearError();
        resetLineBuffers();
        render();
        focusTypingArea();
      } catch (err) {
        showError(err.message);
      }
    }

    async function submitLine() {
      // An empty buffer is not an attempt. Pressing Enter twice used to log a
      // 0% failure, which drags the mean accuracy down and litters the history
      // with records that have an empty user_input -- exactly the shape of the
      // corrupt legacy row that analysis._implausible now has to exclude.
      if (!typed.length) return;
      const durationMs = lineStart ? Date.now() - lineStart : 0;
      const typedFull = keystrokes.map((k) => k.char).join("");
      const sentKeystrokes = keystrokes.slice();
      try {
        const data = await API.post("/api/attempt", {
          typed: typed,
          duration_ms: durationMs,
          typed_full: typedFull,
          keystrokes: sentKeystrokes,
        });
        clearError();
        snapshot = data.state;
        // The right rail freezes on exactly what the server said, and holds
        // it until the next keystroke -- never a number this page computed.
        heldRailValues = {
          wpm: data.result.wpm,
          accuracy: data.result.accuracy,
          passed: data.result.passed,
        };
        lastAttemptKeystrokes = sentKeystrokes;
        fillLastLineDetail(data.result, sentKeystrokes);
        resetLineBuffersKeepHeld();
        render();
        focusTypingArea();
        refreshWorstKeys();
      } catch (err) {
        showError(err.message);
      }
    }

    // Like resetLineBuffers, but preserves heldRailValues -- used right after
    // a submit, where the rail must keep showing the finished line's figures
    // until the player starts the next one.
    function resetLineBuffersKeepHeld() {
      typed = "";
      keystrokes = [];
      lineStart = null;
      flashIndex = null;
      setTyping(false);
      updateLiveRail();
    }

    function fillLastLineDetail(result, sentKeystrokes) {
      const s = snapshot.settings;
      els.detailWpm.textContent = result.wpm.toFixed(0);
      els.detailAcc.textContent = (result.accuracy * 100).toFixed(0) + "%";
      els.detailAcc.className = "n" + (result.accuracy >= s.min_accuracy ? " good" : " bad");

      let verdict = "not required";
      let cls = "";
      if (result.passed) {
        verdict = "passed";
        cls = "good";
      } else if (s.require_accuracy && result.accuracy < s.min_accuracy) {
        verdict = "accuracy short";
        cls = "bad";
      } else if (s.require_wpm && result.wpm < s.min_wpm) {
        verdict = "too slow";
        cls = "bad";
      }
      els.detailVerdict.textContent = verdict;
      els.detailVerdict.className = "n" + (cls ? " " + cls : "");

      if (s.show_criteria) {
        const parts = [];
        if (s.require_accuracy) parts.push(`${(s.min_accuracy * 100).toFixed(0)}%`);
        if (s.require_wpm) parts.push(`${s.min_wpm.toFixed(0)} wpm`);
        els.detailCriteriaLabel.textContent = parts.length ? `against ${parts.join(" · ")}` : "no criteria set";
      } else {
        els.detailCriteriaLabel.textContent = "criteria hidden";
      }

      // Display-only, computed the same way as the mockup's prototype: a
      // stall is a gap over 500ms between two consecutive keystrokes. Never
      // sent anywhere, never affects the score.
      let stalls = 0;
      for (let i = 1; i < sentKeystrokes.length; i++) {
        if (sentKeystrokes[i].ms - sentKeystrokes[i - 1].ms > 500) stalls++;
      }
      els.detailStalls.textContent = String(stalls);
    }

    async function movePosition(delta) {
      try {
        snapshot = await API.post("/api/position", { delta: delta });
        clearError();
        resetLineBuffers();
        render();
        focusTypingArea();
      } catch (err) {
        showError(err.message);
      }
    }

    async function promptJump() {
      if (!snapshot || snapshot.line_count <= 0) return;
      const answer = window.prompt(`Enter line number (1-${snapshot.line_count}):`);
      if (answer === null) return;
      const line = parseInt(answer, 10);
      if (!Number.isFinite(line)) return;
      try {
        snapshot = await API.post("/api/position", { line: line });
        clearError();
        resetLineBuffers();
        render();
        focusTypingArea();
      } catch (err) {
        showError(err.message);
      }
    }

    async function onSettingChanged(event) {
      const input = event.target;
      const key = input.dataset.setting;
      let value;
      if (input.type === "checkbox") {
        value = input.checked;
      } else if (key === "min_accuracy") {
        value = parseFloat(input.value) / 100.0;
      } else if (key === "measure_ch") {
        value = parseInt(input.value, 10);
      } else {
        value = parseFloat(input.value);
      }
      try {
        const settings = await API.post("/api/settings", { [key]: value });
        snapshot.settings = settings;
        clearError();
        renderSettingsForm();
        updateLiveRail();
      } catch (err) {
        showError(err.message);
      } finally {
        focusTypingArea();
      }
    }

    async function onTextPicked(event) {
      const name = event.target.value;
      try {
        snapshot = await API.post("/api/text", { name: name });
        clearError();
        resetLineBuffers();
        lastPosition = null;
        previousLineText = null;
        render();
        focusTypingArea();
      } catch (err) {
        showError(err.message);
      }
    }

    async function onAddText() {
      try {
        const picked = await API.post("/api/pick_path", { kind: "file" });
        if (!picked.path) {
          focusTypingArea();
          return;
        }
        const added = await API.post("/api/text/add", { path: picked.path });
        clearError();
        await refreshTexts();
        snapshot = added.state;
        resetLineBuffers();
        render();
      } catch (err) {
        showError(err.message);
      } finally {
        focusTypingArea();
      }
    }

    async function onResetHistory() {
      try {
        const result = await API.post("/api/history/reset", { scope: "current" });
        clearError();
        await refreshState();
        els.instructions.textContent = `History reset (${result.removed} records). Press Enter to start.`;
      } catch (err) {
        showError(err.message);
      } finally {
        focusTypingArea();
      }
    }

    // ---- review: the closing moment of a session ---------------------------
    //
    // GET /api/review's settled shape:
    //   { session_summary: analysis.session_summary() + "wpm_curve",
    //     deltas: { has_previous, wpm, accuracy, lines_completed, time_typing_s
    //               (each {current, previous, delta, direction: up|down|same}),
    //               worst_category: {category, current_rate, previous_rate,
    //                                 direction: improved|worse|unchanged} },
    //     next_action: {message, kind, target, detail},
    //     streak: {current_streak_days, longest_streak_days} }
    // Still read defensively field-by-field: a first-ever session returns
    // has_previous=false with every delta/direction null, and this renders
    // that as a dash / an omitted "what moved" block rather than throwing or
    // showing a false "0".

    async function openReview() {
      reviewOpen = true;
      closeDrawer();
      els.review.hidden = false;
      renderReview(null);
      try {
        const data = await API.get("/api/review");
        renderReview(data);
      } catch (err) {
        renderReview(null);
      }
    }

    function closeReview() {
      reviewOpen = false;
      els.review.hidden = true;
      focusTypingArea();
    }

    async function startNextFromReview() {
      closeReview();
      if (snapshot && snapshot.state === "READY") {
        await startLine();
      } else {
        focusTypingArea();
      }
    }

    // trendClass: "good" | "down" | "flat" | "" (neutral/unknown)
    function addMovedTile(value, label, trendClass) {
      const div = document.createElement("div");
      const n = document.createElement("div");
      n.className = "n" + (trendClass ? " " + trendClass : " flat");
      n.textContent = value;
      const l = document.createElement("div");
      l.className = "l";
      l.textContent = label;
      div.appendChild(n);
      div.appendChild(l);
      els.reviewMoved.appendChild(div);
    }

    // up/down/same numeric deltas: up is good, down is bad -- true for wpm,
    // accuracy, lines_completed and time_typing_s.
    function trendClassForDirection(direction) {
      if (direction === "up") return "good";
      if (direction === "down") return "down";
      if (direction === "same") return "flat";
      return "";
    }

    // improved/worse/unchanged: an error-rate category, where "improved"
    // means the number went DOWN -- the opposite sense from up/down above.
    function trendClassForCategoryDirection(direction) {
      if (direction === "improved") return "good";
      if (direction === "worse") return "down";
      if (direction === "unchanged") return "flat";
      return "";
    }

    function signed(value, digits, suffix) {
      if (value == null || Number.isNaN(value)) return "—";
      const sign = value > 0 ? "+" : "";
      return `${sign}${value.toFixed(digits)}${suffix || ""}`;
    }

    function renderReview(data) {
      data = data || {};
      const summary = data.session_summary || {};
      const deltas = data.deltas || {};
      const nextAction = data.next_action || {};
      const streak = data.streak || {};

      const bits = [];
      if (summary.duration_s != null) bits.push(`${(summary.duration_s / 60).toFixed(1)} minutes`);
      if (summary.lines_completed != null) bits.push(`${summary.lines_completed} lines`);
      els.reviewSession.textContent = bits.length ? bits.join(" · ") : "—";

      els.reviewWpm.textContent = summary.mean_wpm != null ? Math.round(summary.mean_wpm) : "—";

      const accBits = [];
      if (summary.mean_accuracy != null) accBits.push(`${(summary.mean_accuracy * 100).toFixed(1)}% accuracy`);
      if (summary.passed != null) accBits.push(`${summary.passed} passed`);
      if (summary.failed != null) accBits.push(`${summary.failed} failed`);
      els.reviewAccuracyLine.textContent = accBits.length ? accBits.join(", ") : "—";

      els.reviewMoved.innerHTML = "";
      if (deltas.has_previous) {
        const w = deltas.wpm || {};
        addMovedTile(signed(w.delta, 0), "wpm vs last", trendClassForDirection(w.direction));

        const a = deltas.accuracy || {};
        addMovedTile(
          signed(a.delta != null ? a.delta * 100 : null, 1, "%"),
          "accuracy vs last",
          trendClassForDirection(a.direction)
        );

        const worst = deltas.worst_category || {};
        if (worst.category) {
          addMovedTile(
            worst.current_rate != null ? `${(worst.current_rate * 100).toFixed(1)}%` : "—",
            worst.direction === "unchanged" ? `${worst.category}, unchanged` : worst.category,
            trendClassForCategoryDirection(worst.direction)
          );
        }
      }
      // (Every session, not only a repeat one, gets a streak tile -- it does
      // not depend on has_previous.)
      if (streak.current_streak_days != null) {
        addMovedTile(String(streak.current_streak_days), "day streak", "");
      }

      els.reviewRecommendation.textContent = nextAction.message || "";
    }
  })();
}
