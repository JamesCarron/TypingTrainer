/*
 * stats.js -- the analysis dashboard's whole client. Fetches GET /api/analysis
 * (optionally scoped to one text via GET /api/analysis?text=...) and renders
 * every section from the JSON it gets back. No analysis logic lives here --
 * every number comes from typingtrainer/analysis.py; this file only lays it
 * out (tables, bars, a keyboard heatmap, line charts, a calendar), all as
 * hand-written inline SVG or plain DOM, no chart libraries.
 *
 * Written 2026-09-19 for the "analysis UI" stream of the UI refresh
 * (docs/UI_Refresh_Notes.md, Proposal C / the keybr reference). Every render
 * function is defensive about missing/short data, because a brand-new user
 * with zero attempts must see a sensible page, not a broken one.
 */

(function () {
  "use strict";

  //: The date keystroke capture went in (docs/UI_Refresh_Notes.md, decision 2)
  //: -- quoted in every "not enough data yet" message for the speed section,
  //: so the user knows why an attempt made last month has no timing.
  const KEYSTROKE_CAPTURE_START = "2026-09-19";

  const els = {};

  function $(id) {
    return document.getElementById(id);
  }

  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    els.textFilter = $("text-filter");
    els.loadError = $("load-error");

    els.textFilter.addEventListener("change", () => loadAndRender(els.textFilter.value || null));

    try {
      const texts = await fetchJSON("/api/texts");
      els.textFilter.innerHTML = "";
      const allOption = document.createElement("option");
      allOption.value = "";
      allOption.textContent = "All texts";
      els.textFilter.appendChild(allOption);
      for (const t of texts.texts || []) {
        const option = document.createElement("option");
        option.value = t.name;
        option.textContent = t.name;
        els.textFilter.appendChild(option);
      }
    } catch (err) {
      // The text picker is a convenience; a failure here should not block the
      // report itself from loading with "all texts".
    }

    await loadAndRender(null);
  }

  async function fetchJSON(path) {
    const res = await fetch(path);
    let data;
    try {
      data = await res.json();
    } catch (err) {
      throw new Error(`bad response (${res.status})`);
    }
    if (!res.ok) {
      throw new Error((data && data.error) || `request failed (${res.status})`);
    }
    return data;
  }

  async function loadAndRender(textName) {
    els.loadError.hidden = true;
    try {
      const path = textName ? `/api/analysis?text=${encodeURIComponent(textName)}` : "/api/analysis";
      const report = await fetchJSON(path);
      renderReport(report);
    } catch (err) {
      els.loadError.hidden = false;
      els.loadError.textContent = `Could not load the analysis report: ${err.message}`;
    }
    await loadAndRenderPractice(textName);
  }

  async function loadAndRenderPractice(textName) {
    const msg = $("practice-message");
    try {
      const path = textName ? `/api/practice?text=${encodeURIComponent(textName)}` : "/api/practice";
      const plan = await fetchJSON(path);
      renderPractice(plan);
    } catch (err) {
      msg.hidden = false;
      msg.textContent = `Could not load the practice plan: ${err.message}`;
    }
  }

  async function fetchPost(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data;
    try {
      data = await res.json();
    } catch (err) {
      throw new Error(`bad response (${res.status})`);
    }
    if (!res.ok) {
      throw new Error((data && data.error) || `request failed (${res.status})`);
    }
    return data;
  }

  // ---- small shared helpers -------------------------------------------------

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function pct(x, digits) {
    if (x == null) return "–";
    return (x * 100).toFixed(digits == null ? 1 : digits) + "%";
  }

  function num(x, digits) {
    if (x == null) return "–";
    return x.toFixed(digits == null ? 0 : digits);
  }

  function emptyNote(text) {
    return `<p class="empty-note">${escapeHtml(text)}</p>`;
  }

  function speedEmptyNote(what) {
    return emptyNote(
      `Not enough data yet for ${what}. Keep typing — these need the keystroke timing ` +
        `recorded since ${KEYSTROKE_CAPTURE_START}.`
    );
  }

  /**
   * A horizontal bar chart as a small table of rows: label, a filled track,
   * and a formatted value. `rows` is already sorted/limited by the caller.
   */
  function barChart(rows, { label, value, display, maxValue, errorStyle }) {
    if (!rows.length) return "";
    const max = maxValue != null ? maxValue : Math.max(...rows.map(value));
    const safeMax = max > 0 ? max : 1;
    const body = rows
      .map((row) => {
        const v = value(row);
        const widthPct = Math.max(0, Math.min(100, (v / safeMax) * 100));
        const fillClass = errorStyle ? "bar-fill bar-fill-error" : "bar-fill";
        return `
          <div class="bar-row">
            <div class="bar-label" title="${escapeHtml(label(row))}">${escapeHtml(label(row))}</div>
            <div class="bar-track"><div class="${fillClass}" style="width:${widthPct.toFixed(1)}%"></div></div>
            <div class="bar-value">${escapeHtml(display(row))}</div>
          </div>`;
      })
      .join("");
    return `<div class="bar-chart">${body}</div>`;
  }

  function table(columns, rows) {
    if (!rows.length) return "";
    const head = columns.map((c) => `<th>${escapeHtml(c.label)}</th>`).join("");
    const body = rows
      .map((row) => {
        const cells = columns
          .map((c) => `<td class="${c.num ? "num" : ""} ${c.mono ? "mono" : ""}">${c.render(row)}</td>`)
          .join("");
        return `<tr>${cells}</tr>`;
      })
      .join("");
    return `<table class="stats-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  // ---- the report -------------------------------------------------------------

  function renderReport(report) {
    renderTiles(report.progress.overall_stats, report.data_coverage);
    renderConfusionTable(report.weak_points.confusion_pairs);
    renderProblemWords(report.weak_points.problem_words);
    renderErrorCategories(report.weak_points.error_categories);
    renderHeatmap(report.weak_points.character_error_rates);
    renderSlowKeys(report.speed.key_latencies, report.data_coverage);
    renderSlowBigrams(report.speed.bigram_latencies, report.data_coverage);
    renderSameFinger(report.speed.same_finger_bigrams, report.data_coverage);
    renderRhythm(report.speed.rhythm, report.data_coverage);
    renderErrorTiming(report.speed.error_timing, report.data_coverage);
    renderLearningCurve(report.progress.learning_curve);
    renderAttemptsPerLine(report.progress.attempts_per_line);
    renderCalendar(report.progress.daily_activity);
  }

  // ---- all-time tiles -----------------------------------------------------------

  function renderTiles(overall, coverage) {
    const tiles = [
      [overall.total_attempts, "attempts"],
      [`${(overall.total_duration_s / 60).toFixed(0)}m`, "time typing"],
      [overall.top_wpm != null ? overall.top_wpm.toFixed(0) : "–", "top wpm"],
      [overall.mean_wpm != null ? overall.mean_wpm.toFixed(0) : "–", "mean wpm"],
      [pct(overall.top_accuracy, 0), "top accuracy"],
      [pct(overall.mean_accuracy, 0), "mean accuracy"],
      [overall.current_streak_days, "current streak (days)"],
      [overall.longest_streak_days, "longest streak (days)"],
    ];
    $("tiles").innerHTML = tiles
      .map(
        ([value, label]) =>
          `<div class="tile"><div class="tile-value">${escapeHtml(value)}</div><div class="tile-label">${escapeHtml(label)}</div></div>`
      )
      .join("");
    if (overall.total_attempts === 0) {
      $("tiles").innerHTML += emptyNote("No attempts recorded yet. Type a few lines on the typing page, then come back here.");
    }
  }

  // ---- weak points ---------------------------------------------------------------

  function renderConfusionTable(confusion) {
    const el = $("confusion-table");
    const rows = confusion.pairs.slice(0, 20);
    if (!rows.length) {
      el.innerHTML = emptyNote(
        "No confusions found yet. This needs a handful of attempts on lines of similar length to the target."
      );
      return;
    }
    el.innerHTML = table(
      [
        { label: "You meant", mono: true, render: (r) => (r.intended === " " ? "(space)" : escapeHtml(r.intended)) },
        { label: "You typed", mono: true, render: (r) => (r.typed === " " ? "(space)" : escapeHtml(r.typed)) },
        { label: "Times", num: true, render: (r) => r.count },
      ],
      rows
    );
  }

  function renderProblemWords(words) {
    const el = $("problem-words");
    const rows = words.words.slice(0, 20);
    if (!rows.length) {
      el.innerHTML = emptyNote("No repeatedly-mistyped words found yet.");
      return;
    }
    el.innerHTML = table(
      [
        { label: "Word", mono: true, render: (r) => escapeHtml(r.word) },
        { label: "Times mistyped", num: true, render: (r) => r.count },
        { label: "Example you typed", mono: true, render: (r) => escapeHtml(r.example_typed) },
      ],
      rows
    );
  }

  function renderErrorCategories(categories) {
    const el = $("error-categories");
    const rows = categories.categories;
    if (!rows.length) {
      el.innerHTML = emptyNote("No error-category data yet.");
      return;
    }
    el.innerHTML = barChart(rows, {
      label: (r) => r.category,
      value: (r) => r.error_rate,
      display: (r) => `${pct(r.error_rate, 1)} of ${r.seen}`,
      maxValue: Math.max(0.01, ...rows.map((r) => r.error_rate)),
      errorStyle: true,
    });
  }

  // ---- keyboard heatmap -----------------------------------------------------------

  //: Physical key groups: [unshifted, shifted] variants that land on the same
  //: key, so e.g. '1' and '!' are combined into one tile's error rate.
  const KEY_ROWS = [
    [
      ["1", "!"], ["2", "@"], ["3", "#"], ["4", "$"], ["5", "%"],
      ["6", "^"], ["7", "&"], ["8", "*"], ["9", "("], ["0", ")"],
      ["-", "_"], ["=", "+"],
    ],
    [
      ["q", "Q"], ["w", "W"], ["e", "E"], ["r", "R"], ["t", "T"],
      ["y", "Y"], ["u", "U"], ["i", "I"], ["o", "O"], ["p", "P"],
      ["[", "{"], ["]", "}"],
    ],
    [
      ["a", "A"], ["s", "S"], ["d", "D"], ["f", "F"], ["g", "G"],
      ["h", "H"], ["j", "J"], ["k", "K"], ["l", "L"], [";", ":"], ["'", "\""],
    ],
    [
      ["z", "Z"], ["x", "X"], ["c", "C"], ["v", "V"], ["b", "B"],
      ["n", "N"], ["m", "M"], [",", "<"], [".", ">"], ["/", "?"],
    ],
  ];

  function heatColor(rate) {
    // Error rates on real prose are usually small (a few percent), so the
    // raw rate barely tints anything -- scale it up for visibility while
    // still capping at fully saturated. This is a display choice, not a
    // statistic: the exact rate is always in the hover title.
    const visual = Math.max(0, Math.min(1, rate * 4));
    const percentage = (visual * 100).toFixed(0);
    return `color-mix(in srgb, var(--tt-incorrect) ${percentage}%, var(--tt-bg))`;
  }

  function renderHeatmap(charRates) {
    const el = $("keyboard-heatmap");
    const byChar = new Map(charRates.characters.map((r) => [r.char, r]));

    function combine(variants) {
      let seen = 0;
      let mistyped = 0;
      for (const ch of variants) {
        const r = byChar.get(ch);
        if (r) {
          seen += r.seen;
          mistyped += r.mistyped;
        }
      }
      return { seen, mistyped, error_rate: seen ? mistyped / seen : null };
    }

    const rowsHtml = KEY_ROWS.map((row) => {
      const keys = row
        .map((variants) => {
          const label = variants[0];
          const stats = combine(variants);
          const style = stats.seen ? `background-color:${heatColor(stats.error_rate)};` : "";
          const cls = stats.seen ? "kb-key" : "kb-key kb-unseen";
          const title = stats.seen
            ? `${label}: seen ${stats.seen}, mistyped ${stats.mistyped} (${pct(stats.error_rate, 1)})`
            : `${label}: not seen yet`;
          return `<div class="${cls}" style="${style}" title="${escapeHtml(title)}">${escapeHtml(label)}</div>`;
        })
        .join("");
      return `<div class="kb-row">${keys}</div>`;
    }).join("");

    const spaceStats = combine([" "]);
    const spaceStyle = spaceStats.seen ? `background-color:${heatColor(spaceStats.error_rate)};` : "";
    const spaceTitle = spaceStats.seen
      ? `space: seen ${spaceStats.seen}, mistyped ${spaceStats.mistyped} (${pct(spaceStats.error_rate, 1)})`
      : "space: not seen yet";
    const spaceRow = `<div class="kb-row"><div class="kb-key kb-space${spaceStats.seen ? "" : " kb-unseen"}" style="${spaceStyle}" title="${escapeHtml(spaceTitle)}">space</div></div>`;

    if (charRates.attempts_considered === 0) {
      el.innerHTML = emptyNote("No usable attempts yet for the heatmap.");
      return;
    }
    el.innerHTML =
      rowsHtml +
      spaceRow +
      `<div class="kb-legend"><span>low error</span><span class="kb-legend-swatch"></span><span>high error</span></div>`;
  }

  // ---- speed ------------------------------------------------------------------------

  function renderSlowKeys(keyLatencies, coverage) {
    const el = $("slow-keys");
    if (coverage.instrumented_attempts === 0) {
      el.innerHTML = speedEmptyNote("slowest-key timing");
      return;
    }
    const rows = keyLatencies.keys.slice(0, 15);
    if (!rows.length) {
      el.innerHTML = emptyNote("No key timing recorded yet.");
      return;
    }
    el.innerHTML =
      emptyNote("Mean time, in milliseconds, since the previous keystroke -- higher means slower.") +
      barChart(rows, {
        label: (r) => (r.char === " " ? "(space)" : r.char),
        value: (r) => r.mean_ms,
        display: (r) => `${num(r.mean_ms)}ms (n=${r.count})`,
      });
  }

  function renderSlowBigrams(bigramLatencies, coverage) {
    const el = $("slow-bigrams");
    if (coverage.instrumented_attempts === 0) {
      el.innerHTML = speedEmptyNote("bigram (letter-pair) timing");
      return;
    }
    const rows = bigramLatencies.bigrams.slice(0, 15);
    if (!rows.length) {
      el.innerHTML = emptyNote(
        `No transition occurs at least ${bigramLatencies.min_occurrences} times yet -- keep typing to build this up.`
      );
      return;
    }
    el.innerHTML = barChart(rows, {
      label: (r) => `${r.prev === " " ? "␣" : r.prev}${r.char === " " ? "␣" : r.char}`,
      value: (r) => r.mean_ms,
      display: (r) => `${num(r.mean_ms)}ms (n=${r.count})`,
    });
  }

  function renderSameFinger(sameFinger, coverage) {
    const el = $("same-finger");
    if (coverage.instrumented_attempts === 0) {
      el.innerHTML = speedEmptyNote("same-finger bigram timing");
      return;
    }
    if (sameFinger.same_finger_mean_ms == null || sameFinger.all_bigrams_mean_ms == null) {
      el.innerHTML = emptyNote("Not enough repeated same-finger transitions yet to compare.");
      return;
    }
    const diffPct = ((sameFinger.same_finger_mean_ms / sameFinger.all_bigrams_mean_ms - 1) * 100).toFixed(0);
    const sentence =
      diffPct > 0
        ? `Same-finger transitions average ${num(sameFinger.same_finger_mean_ms)}ms, ${diffPct}% slower than the ${num(
            sameFinger.all_bigrams_mean_ms
          )}ms average across all transitions -- the lateral reach without another finger to help is costing you time.`
        : `Same-finger transitions average ${num(sameFinger.same_finger_mean_ms)}ms, about the same as the ${num(
            sameFinger.all_bigrams_mean_ms
          )}ms average across all transitions.`;
    const rows = sameFinger.pairs.slice(0, 10);
    el.innerHTML =
      `<p class="section-note">${escapeHtml(sentence)}</p>` +
      (rows.length
        ? barChart(rows, {
            label: (r) => `${r.prev}${r.char} (${r.finger})`,
            value: (r) => r.mean_ms,
            display: (r) => `${num(r.mean_ms)}ms (n=${r.count})`,
          })
        : "");
  }

  function renderRhythm(rhythm, coverage) {
    const el = $("rhythm");
    if (coverage.instrumented_attempts === 0) {
      el.innerHTML = speedEmptyNote("rhythm and stall data");
      return;
    }
    const sentence = `Average gap between keystrokes: ${num(rhythm.mean_ms)}ms, varying by ±${num(
      rhythm.stdev_ms
    )}ms. A stall is any gap over ${num(rhythm.stall_threshold_ms, 0)}ms -- ${rhythm.stall_count} of those found, across ${
      rhythm.instrumented_attempts
    } instrumented attempts.`;
    let stallsHtml = "";
    if (rhythm.stalls.length) {
      const rows = rhythm.stalls.slice(0, 10);
      stallsHtml = table(
        [
          { label: "Line", mono: true, render: (r) => escapeHtml(r.key) },
          { label: "Position", num: true, render: (r) => r.position },
          { label: "Char", mono: true, render: (r) => (r.char === " " ? "(space)" : escapeHtml(r.char)) },
          { label: "Gap (ms)", num: true, render: (r) => num(r.gap_ms) },
        ],
        rows
      );
    }
    el.innerHTML = `<p class="section-note">${escapeHtml(sentence)}</p>${stallsHtml}`;
  }

  function renderErrorTiming(errorTiming, coverage) {
    const el = $("error-timing");
    if (coverage.instrumented_attempts === 0 || errorTiming.interpretation === "insufficient data") {
      el.innerHTML = speedEmptyNote("the error-timing finding");
      return;
    }
    const sentence = `Mean gap before a wrong keystroke: ${num(errorTiming.mean_gap_before_error_ms)}ms. Mean gap before a correct one: ${num(
      errorTiming.mean_gap_before_correct_ms
    )}ms. ${errorTiming.interpretation}.`;
    el.innerHTML = `<p class="section-note">${escapeHtml(sentence)}</p>`;
  }

  // ---- progress -------------------------------------------------------------------

  function renderLearningCurve(curve) {
    const el = $("learning-curve");
    const points = curve.points;
    if (points.length < 2) {
      el.innerHTML = emptyNote("Not enough scored attempts yet to draw a learning curve.");
      return;
    }
    const width = 900;
    const height = 180;
    const padL = 36;
    const padB = 20;
    const padT = 10;
    const padR = 10;
    const wpms = points.map((p) => p.wpm);
    const rolling = points.map((p) => p.rolling_mean_wpm);
    const maxWpm = Math.max(...wpms, ...rolling.filter((v) => v != null));
    const minWpm = 0;
    const xStep = (width - padL - padR) / (points.length - 1);
    const yFor = (v) => height - padB - ((v - minWpm) / (maxWpm - minWpm || 1)) * (height - padT - padB);
    const xFor = (i) => padL + i * xStep;

    const toPoly = (values) =>
      values
        .map((v, i) => (v == null ? null : `${xFor(i).toFixed(1)},${yFor(v).toFixed(1)}`))
        .filter((v) => v)
        .join(" ");

    const gridY = [0, 0.5, 1].map((frac) => {
      const v = maxWpm * frac;
      const y = yFor(v);
      return `<line class="line-chart-axis" x1="${padL}" y1="${y.toFixed(1)}" x2="${width - padR}" y2="${y.toFixed(1)}" />` +
        `<text class="line-chart-label" x="4" y="${(y + 3).toFixed(1)}">${v.toFixed(0)}</text>`;
    }).join("");

    const svg = `
      <svg class="line-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="WPM per attempt over time, with a rolling mean">
        ${gridY}
        <line class="line-chart-axis" x1="${padL}" y1="${height - padB}" x2="${width - padR}" y2="${height - padB}" />
        <polyline class="line-chart-series wpm" points="${toPoly(wpms)}" />
        <polyline class="line-chart-series rolling" points="${toPoly(rolling)}" />
        <text class="line-chart-label" x="${padL}" y="${height - 4}">oldest</text>
        <text class="line-chart-label" x="${width - padR - 40}" y="${height - 4}">most recent</text>
      </svg>`;

    el.innerHTML =
      svg +
      `<div class="chart-legend">
        <span><span class="chart-legend-swatch" style="background:var(--tt-sub)"></span>wpm per attempt</span>
        <span><span class="chart-legend-swatch" style="background:var(--tt-accent)"></span>rolling mean (window of ${curve.window})</span>
      </div>`;
  }

  function renderAttemptsPerLine(perLine) {
    const el = $("attempts-per-line");
    const rows = perLine.lines.slice(0, 15);
    if (!rows.length) {
      el.innerHTML = emptyNote("No line-attempt data yet.");
      return;
    }
    el.innerHTML =
      `<p class="section-note">The lines taking the most attempts to pass -- the walls in the book.</p>` +
      barChart(rows, {
        label: (r) => r.line,
        value: (r) => r.attempts,
        display: (r) => `${r.attempts} (${r.passed} passed)`,
      });
  }

  // ---- practice (the improvement loop) --------------------------------------------

  //: Sections that only make sense once there is enough data -- hidden, in favour
  //: of the plan's own message, when practice_plan reports has_enough_data: false.
  const PRACTICE_DATA_WRAPS = [
    "practice-targets-wrap",
    "practice-drill-wrap",
    "practice-hard-lines-wrap",
    "practice-trouble-words-wrap",
  ];

  function renderPractice(plan) {
    const msg = $("practice-message");
    if (!plan.has_enough_data) {
      msg.hidden = false;
      msg.textContent = plan.message || "Not enough data yet.";
      PRACTICE_DATA_WRAPS.forEach((id) => {
        $(id).hidden = true;
      });
    } else {
      msg.hidden = true;
      PRACTICE_DATA_WRAPS.forEach((id) => {
        $(id).hidden = false;
      });
      renderPracticeTargets(plan.targets);
      renderPracticeDrill(plan.drill);
      renderPracticeHardLines(plan.hard_lines, plan.text_name);
      renderPracticeTroubleWords(plan.trouble_words);
    }
    // The criteria suggestion is always present, even with zero attempts (it
    // just says so) -- so it stays outside the has_enough_data branch.
    renderPracticeCriteria(plan.criteria_suggestion);
  }

  function renderPracticeTargets(targets) {
    const el = $("practice-targets");
    if (!targets.length) {
      el.innerHTML = emptyNote("No ranked weak targets yet.");
      return;
    }
    el.innerHTML = table(
      [
        { label: "Kind", mono: true, render: (r) => escapeHtml(r.kind) },
        { label: "Target", mono: true, render: (r) => escapeHtml(r.target) },
        { label: "Why", render: (r) => escapeHtml(r.reason) },
      ],
      targets
    );
  }

  function renderPracticeDrill(drill) {
    const el = $("practice-drill");
    if (!drill) {
      el.innerHTML = emptyNote("No drill line could be generated from the current weak targets.");
      return;
    }
    el.innerHTML =
      `<p class="practice-drill-line mono">${escapeHtml(drill)}</p>` +
      `<div><button type="button" class="practice-btn" id="start-drill-btn">Type this drill</button></div>`;
    $("start-drill-btn").addEventListener("click", async () => {
      const btn = $("start-drill-btn");
      btn.disabled = true;
      try {
        await fetchPost("/api/drill", { line: drill });
        window.location.href = "/";
      } catch (err) {
        btn.disabled = false;
        alert(`Could not start the drill: ${err.message}`);
      }
    });
  }

  function renderPracticeHardLines(hardLines, textName) {
    const el = $("practice-hard-lines");
    if (!textName) {
      el.innerHTML = emptyNote("Select a specific text above (not \"All texts\") to find hard lines from its book.");
      return;
    }
    if (!hardLines.length) {
      el.innerHTML = emptyNote("No upcoming line in this book stands out as especially dense in your weak targets.");
      return;
    }
    el.innerHTML = hardLines
      .map((h, i) => {
        const exercises = h.targets_matched
          .map((m) => `${escapeHtml(m.target === " " ? "(space)" : m.target)} &times;${m.count}`)
          .join(", ");
        return `
          <div class="practice-hard-line">
            <p class="practice-hard-line-text mono">${escapeHtml(h.line)}</p>
            <p class="section-note">Line ${h.line_index + 1} of the book &middot; exercises: ${exercises}</p>
            <button type="button" class="practice-btn jump-line-btn" data-line="${h.line_index + 1}">Jump to this line</button>
          </div>`;
      })
      .join("");
    el.querySelectorAll(".jump-line-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await fetchPost("/api/position", { line: parseInt(btn.dataset.line, 10) });
          window.location.href = "/";
        } catch (err) {
          btn.disabled = false;
          alert(`Could not jump to that line: ${err.message}`);
        }
      });
    });
  }

  function renderPracticeTroubleWords(words) {
    const el = $("practice-trouble-words");
    if (!words.length) {
      el.innerHTML = emptyNote("No repeatedly-mistyped words on the watchlist yet.");
      return;
    }
    el.innerHTML = table(
      [
        { label: "Word", mono: true, render: (r) => escapeHtml(r.word) },
        { label: "Times mistyped", num: true, render: (r) => r.count },
        { label: "A wrong version you typed", mono: true, render: (r) => escapeHtml(r.common_wrong_version) },
      ],
      words
    );
  }

  function renderPracticeCriteria(sugg) {
    const el = $("practice-criteria");
    const changed =
      sugg.proposed_min_wpm !== sugg.current_min_wpm || sugg.proposed_min_accuracy !== sugg.current_min_accuracy;
    el.innerHTML =
      `<p class="section-note">${escapeHtml(sugg.reasoning)}</p>` +
      `<table class="stats-table practice-criteria-table">
        <thead><tr><th></th><th>Min WPM</th><th>Min accuracy</th></tr></thead>
        <tbody>
          <tr><td>Current</td><td class="num">${num(sugg.current_min_wpm)}</td><td class="num">${pct(sugg.current_min_accuracy, 0)}</td></tr>
          <tr><td>Proposed</td><td class="num">${num(sugg.proposed_min_wpm)}</td><td class="num">${pct(sugg.proposed_min_accuracy, 0)}</td></tr>
        </tbody>
      </table>` +
      (changed ? `<button type="button" class="practice-btn" id="apply-criteria-btn">Apply</button>` : "");
    if (changed) {
      $("apply-criteria-btn").addEventListener("click", async () => {
        const btn = $("apply-criteria-btn");
        btn.disabled = true;
        try {
          await fetchPost("/api/criteria/apply", {
            min_wpm: sugg.proposed_min_wpm,
            min_accuracy: sugg.proposed_min_accuracy,
          });
          btn.textContent = "Applied";
        } catch (err) {
          btn.disabled = false;
          alert(`Could not apply the new criteria: ${err.message}`);
        }
      });
    }
  }

  function renderCalendar(daily) {
    const el = $("calendar");
    const days = daily.days;
    if (!days.length) {
      el.innerHTML = emptyNote("No dated attempts yet to build a practice calendar.");
      return;
    }
    const maxAttempts = Math.max(...days.map((d) => d.attempts));
    const cells = days
      .map((d) => {
        const intensity = maxAttempts ? d.attempts / maxAttempts : 0;
        const bg = intensity ? `color-mix(in srgb, var(--tt-accent) ${(intensity * 100).toFixed(0)}%, var(--tt-bg))` : "";
        const title = `${d.date}: ${d.attempts} attempts, ${(d.duration_s / 60).toFixed(1)}m, mean ${num(d.mean_wpm)} wpm`;
        return `<div class="calendar-day" style="${bg ? `background-color:${bg};` : ""}" title="${escapeHtml(title)}"></div>`;
      })
      .join("");
    el.innerHTML =
      `<p class="section-note">${days.length} active day${days.length === 1 ? "" : "s"}, oldest first, shaded by attempts that day.</p>` +
      `<div class="calendar-grid">${cells}</div>`;
  }
})();
