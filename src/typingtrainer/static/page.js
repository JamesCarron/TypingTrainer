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
 * Rewritten again 2026-09-20 for the reading-surface refresh
 * (docs/mockups/UI_Mockup_Reader_C.html, the agreed design), rendering logic
 * lifted from that prototype's Proto.render/currentMarkup:
 *   - the centre shows several book lines: rows above from GET /api/state's
 *     `previous_lines` (up to 7, in reading order, shorter near the start of
 *     the text -- never padded), the current line unchanged in its own
 *     typing-area/caret machinery, rows below from `visible_lines[1:]`
 *   - each off-current row's opacity is `fade_per_line ** distance`, set
 *     inline per row; the current line is always `font_size_px * 1.32`
 *   - `--face`/`--reading-size` (page.css) are set from the `font_family`/
 *     `font_size_px` settings; FONT_IS_MONO below mirrors
 *     typingtrainer.config.FONT_IS_MONO and is the one place that knows
 *     which faces are fixed-width -- see the substitution rule in
 *     renderLines()
 *   - error marking is one of five styles (ERROR_STYLES), applied as an
 *     `err-*` class on #stage
 *
 * Rewritten again 2026-09-20 for per-user progress (multiple people sharing
 * one machine, no authentication -- just a chosen name, see AGENTS.md):
 *   - nothing ever blocks the page on load. startUserFlow() reads
 *     localStorage["typingtrainer.user"] and POSTs it to /api/user; with
 *     nothing remembered (or that call failing) it POSTs {anonymous: true}
 *     instead, which mints a guest (a name like "Guest 1") -- either way
 *     typing is available immediately, there is no first-run screen
 *   - every localStorage access is wrapped in try/catch (rememberUser) --
 *     it throws in a private window and in some embedded contexts, and the
 *     tool must still work, just asking (anonymously) again next load
 *   - "Switch user" (left drawer) is an ordinary inline control, not a
 *     blocking screen: it expands a list from GET /api/users in place, with
 *     its own Cancel (openSwitchUser/closeSwitchUser)
 *   - "Save progress as..." (left drawer) shows only while the current user
 *     is an unnamed guest -- detected by isGuestName() against the "Guest
 *     <n>" shape the brief describes, since the API does not carry an
 *     explicit is-guest flag -- and calls POST /api/user/rename
 *   - the left rail's STEP/LINE/OF group gains a USER figure, truncated by
 *     CSS (.rf .v.trunc) rather than letting the rail grow for a long name
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

    // Mirrors typingtrainer.config.FONT_FAMILIES / FONT_IS_MONO exactly --
    // this is the one place in the front end that knows which faces are
    // fixed-width. It has to live here (not just in config.py) because the
    // substitution rule below (renderLines) is a rendering decision: a
    // proportional face must never show the character the typist actually
    // hit in place of the book's, because the line would reflow under their
    // eye mid-word, while a monospace face can safely show it since every
    // glyph occupies the same box. Keep this in sync with config.py by hand
    // if that list ever changes.
    const FONT_IS_MONO = {
      "Open Sans": false,
      "Work Sans": false,
      "Public Sans": false,
      "Fira Code": true,
      "Roboto Mono": true,
      "Ubuntu Mono": true,
    };
    const DEFAULT_FONT_FAMILY = "Open Sans";
    // Mirrors typingtrainer.config; keep in step by hand.
    const MEASURE_CH_MIN = 50;
    const MEASURE_CH_MAX = 120;
    const DEFAULT_MEASURE_CH = 78;
    const ERROR_STYLES = ["tint", "underline", "dot", "strike", "wavy"];
    const DEFAULT_ERROR_STYLE = "tint";
    // Per-user progress (no authentication -- see AGENTS.md).
    const USER_STORAGE_KEY = "typingtrainer.user";
    // The API does not carry an explicit is-guest flag, so a guest is
    // recognised by the shape the brief specifies a minted name takes.
    const GUEST_NAME_RE = /^Guest \d+$/;
    // Fixed per the agreed design, not a setting: the current line is always
    // this multiple of font_size_px.
    const CURRENT_LINE_EMPHASIS = 1.32;

    function isMonoFamily(family) {
      return !!FONT_IS_MONO[family];
    }

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
    let switchUserOpen = false; // inline list in the left drawer, not a blocking screen

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
      els.rowsAbove = $("rows-above");
      els.rowsBelow = $("rows-below");
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
      els.fontFamilyInput = $("font-family-input");
      els.fontSizeInput = $("font-size-input");
      els.fontSizeVal = $("font-size-val");
      els.visibleLinesInput = $("visible-lines-input");
      els.visibleLinesVal = $("visible-lines-val");
      els.fadePerLineInput = $("fade-per-line-input");
      els.fadePerLineVal = $("fade-per-line-val");
      els.errorStyleInput = $("error-style-input");
      els.resetHistoryBtn = $("reset-history-btn");
      els.finishSessionBtn = $("finish-session-btn");
      els.railUser = $("rail-user");
      els.panelUserName = $("panel-user-name");
      els.switchUserBtn = $("switch-user-btn");
      els.switchUserList = $("switch-user-list");
      els.switchUserUsers = $("switch-user-users");
      els.switchUserCancelBtn = $("switch-user-cancel-btn");
      els.saveProgress = $("save-progress");
      els.saveProgressInput = $("save-progress-input");
      els.saveProgressBtn = $("save-progress-btn");

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

      els.switchUserBtn.addEventListener("click", toggleSwitchUser);
      els.switchUserCancelBtn.addEventListener("click", closeSwitchUser);
      els.saveProgressBtn.addEventListener("click", onSaveProgress);
      els.saveProgressInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          onSaveProgress();
        }
      });

      for (const wing of [els.wingLeft, els.wingRight]) {
        wing.addEventListener("click", (event) => {
          // Only the RAIL toggles the drawer. Enumerating interactive elements
          // to ignore was the wrong way round: it missed <summary>, headings,
          // the slider track's padding and any plain text, so clicking the
          // Advanced disclosure -- or anywhere between two controls -- closed
          // the drawer out from under the person using it. A click anywhere
          // inside an open panel is a click on its contents, full stop.
          if (event.target.closest(".panel")) return;
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
      // Same live-preview treatment for the Advanced sliders: font size and
      // fade repaint the surface immediately; visible-lines re-slices the
      // rows already in hand (it never asks the server for more than the up
      // to 7 previous_lines / visible_lines it already sent).
      els.fontSizeInput.addEventListener("input", () => {
        applyReadingSurfaceCss();
        els.fontSizeVal.textContent = els.fontSizeInput.value;
      });
      els.fadePerLineInput.addEventListener("input", () => {
        els.fadePerLineVal.textContent = parseFloat(els.fadePerLineInput.value).toFixed(2);
        renderLines();
      });
      els.visibleLinesInput.addEventListener("input", () => {
        els.visibleLinesVal.textContent = els.visibleLinesInput.value;
        renderLines();
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

      await startUserFlow();
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

    // The measure has to resolve to ONE width for the whole reading column.
    // Expressing it as `Nch` in CSS did not: `ch` is relative to the element
    // it is used on, and the current line is 1.32x the size of the rows around
    // it, so the same setting gave the current line a cap ~49% wider than its
    // neighbours (1103px against 742px at 86ch) -- and on a narrower window
    // that let the current line run out to the rails while the context stayed
    // short. So measure the character once, in the chosen face at the base
    // reading size, and hand every block the same pixel width.
    function measureCharWidth(family, sizePx) {
      const canvas = measureCharWidth._canvas ||
        (measureCharWidth._canvas = document.createElement("canvas"));
      const ctx = canvas.getContext("2d");
      ctx.font = sizePx + "px '" + family + "'";
      const w = ctx.measureText("0").width;
      // A face that has not finished loading measures as the fallback; 0.5em
      // is a reasonable stand-in until the fonts settle and we are called again.
      return w > 0 ? w : sizePx * 0.5;
    }

    function applyMeasure(chValue) {
      const n = parseInt(chValue, 10);
      const clamped = Number.isFinite(n)
        ? Math.min(MEASURE_CH_MAX, Math.max(MEASURE_CH_MIN, n))
        : DEFAULT_MEASURE_CH;
      // The top of the slider means FULL, not "120 characters": the request was
      // that the text can reach the rails, and how many characters that takes
      // depends on the face, the size and the window. Below the top it is an
      // honest character count.
      const isFull = clamped >= MEASURE_CH_MAX;
      const px = clamped * measureCharWidth(currentFontFamily(), currentFontSizePx());
      // min(..., 100%) is what stops it ever spanning past the rails, on any
      // screen size or display scaling: the column can reach them and stop.
      els.stage.style.setProperty(
        "--measure",
        isFull ? "100%" : "min(" + px.toFixed(1) + "px, 100%)"
      );
      els.measureInput.value = String(clamped);
      // Say "full" when the window has clamped the width away, so the number
      // never claims a measure the screen is not giving.
      //
      // Measured against the CENTRE column, not the rendered line, and read
      // synchronously. Two traps were hit getting here: the line itself has no
      // width yet when this runs from render(), and deferring the read to
      // requestAnimationFrame fixed nothing because rAF callbacks do not run
      // at all while the tab is in the background -- the label simply stayed
      // stale. The centre is always laid out, and reading clientWidth flushes
      // layout synchronously, so this works whether the tab is visible or not.
      let available = 0;
      if (els.centre) {
        const cs = window.getComputedStyle(els.centre);
        available =
          els.centre.clientWidth -
          (parseFloat(cs.paddingLeft) || 0) -
          (parseFloat(cs.paddingRight) || 0);
      }
      els.measureVal.textContent =
        isFull || (available > 0 && px > available + 1) ? "full" : String(clamped);
    }

    function render() {
      if (!snapshot) return;

      // The settings form goes FIRST: the reading surface reads its row count,
      // fade and face off those controls so a slider can preview live while it
      // is dragged, which means the controls must already hold the server's
      // values before the first paint. Rendering them afterwards left the very
      // first paint using the markup's own defaults -- nine rows where the
      // setting said five -- and nothing re-rendered to correct it.
      renderSettingsForm();
      renderLeftRail();
      renderUserPanel();
      renderLines();
      renderInstructions();
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

    // ---- reading-surface control values -------------------------------
    //
    // The Advanced settings inputs are the single source of truth for how
    // the surface is drawn -- same pattern as the existing measure_ch
    // slider (applyMeasure): renderSettingsForm() keeps the inputs synced
    // to snapshot.settings, and rendering always reads the *inputs*, so a
    // drag in progress (before "change" fires and persists it) previews
    // immediately without waiting on a round trip.

    function currentFontFamily() {
      const v = els.fontFamilyInput && els.fontFamilyInput.value;
      return v && v in FONT_IS_MONO ? v : DEFAULT_FONT_FAMILY;
    }

    function currentFontSizePx() {
      const n = els.fontSizeInput ? parseInt(els.fontSizeInput.value, 10) : NaN;
      return Number.isFinite(n) ? n : 17;
    }

    function currentVisibleLines() {
      const n = els.visibleLinesInput ? parseInt(els.visibleLinesInput.value, 10) : NaN;
      return Number.isFinite(n) && n > 0 ? n : 5;
    }

    function currentFadePerLine() {
      const n = els.fadePerLineInput ? parseFloat(els.fadePerLineInput.value) : NaN;
      return Number.isFinite(n) ? n : 0.6;
    }

    function currentErrorStyle() {
      const v = els.errorStyleInput && els.errorStyleInput.value;
      return ERROR_STYLES.includes(v) ? v : DEFAULT_ERROR_STYLE;
    }

    // Sets --face/--reading-size on the stage and the err-* class, without
    // touching the row contents -- called on every settings sync and on
    // every live slider drag.
    function applyReadingSurfaceCss() {
      const family = currentFontFamily();
      const fallback = isMonoFamily(family) ? "monospace" : "sans-serif";
      els.stage.style.setProperty("--face", `"${family}", ${fallback}`);
      els.stage.style.setProperty("--reading-size", currentFontSizePx() + "px");
      const style = currentErrorStyle();
      for (const s of ERROR_STYLES) {
        els.stage.classList.remove("err-" + s);
      }
      els.stage.classList.add("err-" + style);
    }

    function fadeOpacity(distance) {
      return Math.pow(currentFadePerLine(), distance).toFixed(3);
    }

    function renderLines() {
      const visible = (snapshot && snapshot.visible_lines) || [];
      const target = visible[0] || "";
      const mono = isMonoFamily(currentFontFamily());

      els.currentLine.innerHTML = "";
      const matches = diff(typed, target);
      const length = Math.max(typed.length, target.length);
      for (let i = 0; i < length; i++) {
        const span = document.createElement("span");
        const hasTyped = i < typed.length;
        const targetChar = i < target.length ? target[i] : null;
        if (hasTyped) {
          const isMatch = matches[i];
          // Substitution rule: a fixed-width face can show the character the
          // typist actually hit in its place, since every glyph occupies the
          // same box and nothing reflows. A proportional face must never do
          // this -- the line would visibly reflow under the eye mid-word --
          // so it always shows the book's own glyph and marks it instead.
          // See FONT_IS_MONO at the top of this file.
          const glyph = isMatch || mono ? typed[i] : targetChar !== null ? targetChar : typed[i];
          span.textContent = glyph;
          span.className = isMatch ? "char-correct" : "char-incorrect";
          if (!isMatch && (typed[i] === " " || targetChar === " ")) {
            span.classList.add("char-incorrect-space");
          }
        } else {
          span.textContent = target[i];
          span.className = "char-pending";
        }
        if (flashIndex !== null && i === flashIndex) {
          span.classList.add("char-flash");
        }
        els.currentLine.appendChild(span);
      }

      renderRowsAbove();
      renderRowsBelow(visible);
      positionCaret();
    }

    // Rows above the current line, from GET /api/state's `previous_lines`
    // (up to 7, oldest first, closest-to-current last). Genuinely shorter
    // near the start of a text -- rendered as fewer rows, never padded or
    // invented, per docs/Contracts.md ("no state in the page the server
    // does not also hold").
    function renderRowsAbove() {
      if (!els.rowsAbove) return;
      els.rowsAbove.innerHTML = "";
      const previous = (snapshot && Array.isArray(snapshot.previous_lines)) ? snapshot.previous_lines : [];
      const half = Math.floor(currentVisibleLines() / 2);
      const want = Math.min(half, previous.length);
      if (want <= 0) return;
      const shown = previous.slice(previous.length - want); // closest-to-current last
      shown.forEach((line, i) => {
        const distance = shown.length - i; // nearest row above is distance 1
        const div = document.createElement("div");
        div.className = "row-line";
        div.style.opacity = fadeOpacity(distance);
        div.textContent = line;
        els.rowsAbove.appendChild(div);
      });
    }

    // Rows below the current line, from `visible_lines[1:]` -- the current
    // line itself is visible_lines[0] and is rendered separately above.
    function renderRowsBelow(visible) {
      if (!els.rowsBelow) return;
      els.rowsBelow.innerHTML = "";
      const half = Math.floor(currentVisibleLines() / 2);
      const below = visible.slice(1, 1 + half);
      below.forEach((line, i) => {
        const distance = i + 1;
        const div = document.createElement("div");
        div.className = "row-line";
        div.style.opacity = fadeOpacity(distance);
        div.textContent = line;
        els.rowsBelow.appendChild(div);
      });
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
      // Just the key hint. The last line's speed and accuracy used to be
      // appended here as well, which repeated what the right rail already
      // shows live and in more detail -- two places saying the same thing,
      // one of them stale the moment the next keystroke lands.
      els.instructions.textContent =
        snapshot.state === "READY"
          ? "Press Enter to start."
          : "Press Enter to finish or Esc to exit.";
    }

    function renderSettingsForm() {
      const s = snapshot.settings;
      const READING_KEYS = ["font_family", "font_size_px", "visible_lines", "fade_per_line", "error_style"];
      for (const input of document.querySelectorAll("[data-setting]")) {
        const key = input.dataset.setting;
        if (key === "measure_ch" || READING_KEYS.includes(key)) continue; // handled separately below
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

      // Reading-surface Advanced settings: each falls back to its
      // config.py default if a settings payload is missing it (older
      // server, or a value that failed validation upstream).
      if (els.fontFamilyInput) {
        els.fontFamilyInput.value = s.font_family != null && s.font_family in FONT_IS_MONO ? s.font_family : DEFAULT_FONT_FAMILY;
      }
      if (els.fontSizeInput) {
        const size = s.font_size_px != null ? s.font_size_px : 17;
        els.fontSizeInput.value = String(size);
        els.fontSizeVal.textContent = String(size);
      }
      if (els.visibleLinesInput) {
        const lines = s.visible_lines != null ? s.visible_lines : 5;
        els.visibleLinesInput.value = String(lines);
        els.visibleLinesVal.textContent = String(lines);
      }
      if (els.fadePerLineInput) {
        const fade = s.fade_per_line != null ? s.fade_per_line : 0.6;
        els.fadePerLineInput.value = String(fade);
        els.fadePerLineVal.textContent = fade.toFixed(2);
      }
      if (els.errorStyleInput) {
        els.errorStyleInput.value = ERROR_STYLES.includes(s.error_style) ? s.error_style : DEFAULT_ERROR_STYLE;
      }
      applyReadingSurfaceCss();
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

    // ---- per-user progress: no login screen, just a remembered/guest name --
    //
    // Nothing ever blocks the page: startUserFlow runs once at startup,
    // before the first render, and always lands on SOME user (a remembered
    // name, or a freshly minted guest) before typing begins. See the header
    // comment for the shape of POST /api/user and /api/user/rename.

    function isGuestName(name) {
      // Prefer the server's flag: a guest is one the tool minted, not one whose
      // name happens to look like "Guest 7" -- which is a legal thing for a
      // person to call themselves. The pattern stays only as a fallback for a
      // snapshot that predates the flag.
      if (snapshot && typeof snapshot.user_is_guest === "boolean") {
        return snapshot.user_is_guest;
      }
      return /^Guest \d+$/.test(name || "");
    }

    // Wrapped in try/catch everywhere it is called: localStorage throws in a
    // private window and in some embedded contexts, and the tool must still
    // work -- it will just ask (anonymously, silently) again next load.
    function rememberUser(name) {
      try {
        window.localStorage.setItem(USER_STORAGE_KEY, name);
      } catch (err) {
        // ignored -- see above
      }
    }

    async function startUserFlow() {
      let remembered = null;
      try {
        remembered = window.localStorage.getItem(USER_STORAGE_KEY);
      } catch (err) {
        remembered = null;
      }
      try {
        const data = remembered
          ? await API.post("/api/user", { name: remembered })
          : await API.post("/api/user", { anonymous: true });
        rememberUser(data.user);
        await afterUserChosen(data);
      } catch (err) {
        // A remembered name that no longer works (or any other failure) must
        // not strand the page with no user and nothing to type against --
        // fall back to a fresh guest rather than surfacing the error.
        try {
          const data = await API.post("/api/user", { anonymous: true });
          rememberUser(data.user);
          await afterUserChosen(data);
        } catch (err2) {
          showError(err2.message);
        }
      }
    }

    // Common tail for every path that lands on a user (startup, switching,
    // renaming): adopt the snapshot the server returned, refresh the text
    // list and worst-keys for that user, and hand focus back to typing.
    async function afterUserChosen(data) {
      snapshot = data;
      clearError();
      try {
        await refreshTexts();
      } catch (err) {
        // best-effort, same as any other /api/texts failure
      }
      render();
      refreshWorstKeys();
      focusTypingArea();
    }

    function renderUserPanel() {
      const name = snapshot && snapshot.user;
      const label = name || "—";
      if (els.railUser) {
        els.railUser.textContent = label;
        els.railUser.title = name || "";
      }
      if (els.panelUserName) {
        els.panelUserName.textContent = label;
      }
      if (els.saveProgress) {
        els.saveProgress.hidden = !isGuestName(name);
      }
    }

    function userMeta(u) {
      const line = u && u.line != null ? `line ${u.line}` : "not started";
      const attempts = u && typeof u.attempts === "number" ? u.attempts : 0;
      return `${line} · ${attempts} attempt${attempts === 1 ? "" : "s"}`;
    }

    function toggleSwitchUser() {
      if (switchUserOpen) {
        closeSwitchUser();
      } else {
        openSwitchUser();
      }
    }

    async function openSwitchUser() {
      switchUserOpen = true;
      els.switchUserList.hidden = false;
      els.switchUserUsers.innerHTML = "";
      try {
        const data = await API.get("/api/users");
        renderSwitchUserList(data.users, data.current);
      } catch (err) {
        // Defensive: a broken/empty list still leaves Cancel working.
        renderSwitchUserList([], null);
      }
    }

    function closeSwitchUser() {
      switchUserOpen = false;
      els.switchUserList.hidden = true;
      focusTypingArea();
    }

    function renderSwitchUserList(users, current) {
      els.switchUserUsers.innerHTML = "";
      for (const u of users || []) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "switch-user-user-btn";
        if (current && u.name === current) btn.classList.add("current");
        const nameEl = document.createElement("span");
        nameEl.className = "switch-user-user-name";
        nameEl.textContent = u.name;
        const metaEl = document.createElement("span");
        metaEl.className = "switch-user-user-meta";
        metaEl.textContent = userMeta(u);
        btn.appendChild(nameEl);
        btn.appendChild(metaEl);
        btn.addEventListener("click", () => selectExistingUser(u.name));
        els.switchUserUsers.appendChild(btn);
      }
    }

    async function selectExistingUser(name) {
      try {
        const data = await API.post("/api/user", { name: name });
        rememberUser(name);
        closeSwitchUser();
        await afterUserChosen(data);
      } catch (err) {
        showError(err.message);
        focusTypingArea();
      }
    }

    async function onSaveProgress() {
      const raw = els.saveProgressInput.value;
      const name = raw.trim();
      if (!name) {
        showError("Enter a name.");
        return;
      }
      if (name.length > 40) {
        showError("Name is too long (max 40 characters).");
        return;
      }
      const from = snapshot && snapshot.user;
      if (!from) {
        showError("No current user to rename.");
        return;
      }
      try {
        const data = await API.post("/api/user/rename", { from: from, to: name });
        rememberUser(data.user || name);
        els.saveProgressInput.value = "";
        clearError();
        await afterUserChosen(data);
      } catch (err) {
        showError(err.message);
      } finally {
        focusTypingArea();
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
      } else if (key === "measure_ch" || key === "font_size_px" || key === "visible_lines") {
        value = parseInt(input.value, 10);
      } else if (key === "fade_per_line") {
        value = parseFloat(input.value);
      } else if (key === "font_family" || key === "error_style") {
        value = input.value; // strings, straight through
      } else {
        value = parseFloat(input.value);
      }
      try {
        const settings = await API.post("/api/settings", { [key]: value });
        snapshot.settings = settings;
        clearError();
        renderSettingsForm();
        renderLines();
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
