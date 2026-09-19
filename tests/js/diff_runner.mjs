// diff_runner.mjs -- CLI helper for tests/js/test_diff_parity.py.
//
// Loads the real static/page.js (not a copy) via require(), reads a JSON
// array of {target, typed} pairs from stdin, and writes a JSON array of
// {target, typed, matches} back to stdout. Kept separate from the pytest
// file so the invocation is a plain `node diff_runner.mjs <page.js path>`.
//
// Written 2026-09-19 for stage 6 of the TypingTrainer refactor
// (docs/Refactor_Plan.md).

import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);

const pageJsPath = process.argv[2];
if (!pageJsPath) {
  console.error("usage: node diff_runner.mjs <path to page.js>");
  process.exit(2);
}

const { diff } = require(pageJsPath);

const input = readFileSync(0, "utf-8");
const pairs = JSON.parse(input);

const output = pairs.map(({ target, typed }) => ({
  target,
  typed,
  matches: diff(typed, target),
}));

process.stdout.write(JSON.stringify(output));
