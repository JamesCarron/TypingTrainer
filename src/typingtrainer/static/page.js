/*
 * page.js -- the web front end's whole client: keystroke capture, the live
 * per-character diff (for colouring only -- the server is authoritative for
 * scoring, see docs/Contracts.md), and every control that drives the JSON API.
 *
 * Written 2026-09-19 for stage 6 of the TypingTrainer refactor
 * (docs/Refactor_Plan.md), against the API published in docs/Contracts.md.
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
    let typedFull = ""; // raw keystroke record including deleted characters
    let lineStart = null; // Date.now() of the first keystroke on this line

    const els = {};

    function $(id) {
      return document.getElementById(id);
    }

    document.addEventListener("DOMContentLoaded", init);

    async function init() {
      els.typingArea = $("typing-area");
      els.currentLine = $("current-line");
      els.upcomingLines = $("upcoming-lines");
      els.flash = $("flash");
      els.capslock = $("capslock-warning");
      els.instructions = $("instructions");
      els.textName = $("text-name");
      els.positionLabel = $("position-label");
      els.criteria = $("criteria-display");
      els.prevBtn = $("prev-btn");
      els.nextBtn = $("next-btn");
      els.settingsBtn = $("settings-btn");
      els.settingsPanel = $("settings-panel");
      els.textPicker = $("text-picker");
      els.addTextBtn = $("add-text-btn");
      els.resetHistoryBtn = $("reset-history-btn");
      els.errorBar = $("error-bar");

      els.prevBtn.addEventListener("click", () => movePosition(-1));
      els.nextBtn.addEventListener("click", () => movePosition(1));
      els.positionLabel.addEventListener("click", promptJump);
      els.settingsBtn.addEventListener("click", toggleSettings);
      els.textPicker.addEventListener("change", onTextPicked);
      els.addTextBtn.addEventListener("click", onAddText);
      els.resetHistoryBtn.addEventListener("click", onResetHistory);

      for (const input of document.querySelectorAll("[data-setting]")) {
        input.addEventListener("change", onSettingChanged);
      }

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

    // ---- rendering ------------------------------------------------------------

    function render() {
      if (!snapshot) return;

      els.textName.textContent = `"${snapshot.text_name}"`;
      const pct = (snapshot.progress * 100).toFixed(1);
      els.positionLabel.textContent = `${snapshot.position}/${snapshot.line_count} (${pct}%)`;

      renderCriteria();
      renderLines();
      renderInstructions();
      renderSettingsForm();
    }

    function renderCriteria() {
      const s = snapshot.settings;
      els.criteria.innerHTML = "";
      if (!s.show_criteria) return;
      if (s.require_accuracy) {
        const span = document.createElement("span");
        span.className = "criterion";
        span.textContent = `Min Acc: ${(s.min_accuracy * 100).toFixed(0)}%`;
        els.criteria.appendChild(span);
      }
      if (s.require_wpm) {
        const span = document.createElement("span");
        span.className = "criterion";
        span.textContent = `Min WPM: ${s.min_wpm.toFixed(0)}`;
        els.criteria.appendChild(span);
      }
    }

    function renderLines() {
      const visible = snapshot.visible_lines || [];
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
        els.currentLine.appendChild(span);
      }

      els.upcomingLines.innerHTML = "";
      for (const line of visible.slice(1)) {
        const div = document.createElement("div");
        div.className = "upcoming-line";
        div.textContent = line;
        els.upcomingLines.appendChild(div);
      }
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

    function onKeyDown(event) {
      const capsOn = event.getModifierState && event.getModifierState("CapsLock");
      els.capslock.hidden = !capsOn;

      // Do not steal keystrokes typed into a settings field or the jump prompt.
      if (event.target !== els.typingArea && event.target.tagName !== "BODY") {
        if (event.target.matches && event.target.matches("input, select, textarea")) {
          return;
        }
      }

      if (!snapshot) return;

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
      if (event.key === "Escape") {
        event.preventDefault();
        abortLine();
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
        const target = (snapshot.visible_lines && snapshot.visible_lines[0]) || "";
        const nextIndex = typed.length;
        if (
          snapshot.settings.flash_on_mistake &&
          nextIndex < target.length &&
          event.key !== target[nextIndex]
        ) {
          flashMistake();
        }
        typed += event.key;
        typedFull += event.key;
        renderLines();
      }
    }

    function flashMistake() {
      els.flash.classList.add("flash-active");
      window.setTimeout(() => els.flash.classList.remove("flash-active"), 300);
    }

    // ---- actions -----------------------------------------------------------

    async function startLine() {
      try {
        snapshot = await API.post("/api/start");
        clearError();
        typed = "";
        typedFull = "";
        lineStart = Date.now();
        render();
        focusTypingArea();
      } catch (err) {
        showError(err.message);
      }
    }

    async function abortLine() {
      try {
        snapshot = await API.post("/api/abort");
        clearError();
        typed = "";
        typedFull = "";
        render();
        focusTypingArea();
      } catch (err) {
        showError(err.message);
      }
    }

    async function submitLine() {
      const durationMs = lineStart ? Date.now() - lineStart : 0;
      try {
        const data = await API.post("/api/attempt", {
          typed: typed,
          duration_ms: durationMs,
        });
        clearError();
        snapshot = data.state;
        typed = "";
        typedFull = "";
        lineStart = null;
        render();
        focusTypingArea();
      } catch (err) {
        showError(err.message);
      }
    }

    async function movePosition(delta) {
      try {
        snapshot = await API.post("/api/position", { delta: delta });
        clearError();
        typed = "";
        typedFull = "";
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
        typed = "";
        typedFull = "";
        render();
        focusTypingArea();
      } catch (err) {
        showError(err.message);
      }
    }

    function toggleSettings() {
      els.settingsPanel.hidden = !els.settingsPanel.hidden;
      if (!els.settingsPanel.hidden) renderSettingsForm();
    }

    async function onSettingChanged(event) {
      const input = event.target;
      const key = input.dataset.setting;
      let value;
      if (input.type === "checkbox") {
        value = input.checked;
      } else if (key === "min_accuracy") {
        value = parseFloat(input.value) / 100.0;
      } else {
        value = parseFloat(input.value);
      }
      try {
        const settings = await API.post("/api/settings", { [key]: value });
        snapshot.settings = settings;
        clearError();
        renderCriteria();
        renderSettingsForm();
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
        typed = "";
        typedFull = "";
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
        typed = "";
        typedFull = "";
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
  })();
}
