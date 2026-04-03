"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  STALE_REASON_EDITOR,
  STALE_REASON_WORKSPACE,
  normalizedLaunchSpec,
  parseUtcTimestamp,
  resolveWorkspacePath,
  signedInteger,
  staleMessage,
  trimTail,
} = require("../src/support");

test("signedInteger formats positive, zero, and negative values", () => {
  assert.equal(signedInteger(3), "+3");
  assert.equal(signedInteger(0), "0");
  assert.equal(signedInteger(-2), "-2");
  assert.equal(signedInteger(Number.NaN), "0");
});

test("parseUtcTimestamp returns milliseconds for valid UTC strings", () => {
  assert.equal(
    parseUtcTimestamp("2026-04-03T17:00:00Z"),
    Date.parse("2026-04-03T17:00:00Z")
  );
  assert.equal(parseUtcTimestamp("not-a-date"), null);
  assert.equal(parseUtcTimestamp(""), null);
});

test("staleMessage stays explicit for editor and workspace drift", () => {
  assert.equal(
    staleMessage(STALE_REASON_EDITOR),
    "Review data may be stale because there are unsaved editor changes."
  );
  assert.equal(
    staleMessage(STALE_REASON_WORKSPACE),
    "Review data may be stale because the workspace changed after this run."
  );
});

test("normalizedLaunchSpec trims arguments and rejects empty command or cwd", () => {
  assert.deepEqual(
    normalizedLaunchSpec({
      command: "  codeclone-mcp  ",
      args: [" --stdio ", "", "  "],
      cwd: " /tmp/workspace ",
    }),
    {
      command: "codeclone-mcp",
      args: ["--stdio"],
      cwd: "/tmp/workspace",
    }
  );
  assert.throws(
    () => normalizedLaunchSpec({ command: "", args: [], cwd: "/tmp" }),
    /must not be empty/
  );
  assert.throws(
    () => normalizedLaunchSpec({ command: "codeclone-mcp", args: [], cwd: "" }),
    /must not be empty/
  );
});

test("resolveWorkspacePath keeps paths inside the workspace root only", () => {
  const root = "/workspace/repo";
  assert.equal(
    resolveWorkspacePath(root, "src/module.py"),
    "/workspace/repo/src/module.py"
  );
  assert.equal(
    resolveWorkspacePath(root, "./src/../src/module.py"),
    "/workspace/repo/src/module.py"
  );
  assert.equal(resolveWorkspacePath(root, "../outside.py"), null);
  assert.equal(resolveWorkspacePath(root, ""), null);
});

test("trimTail keeps the newest part of long strings", () => {
  assert.equal(trimTail("abcdef", 4), "cdef");
  assert.equal(trimTail("abc", 10), "abc");
  assert.equal(trimTail("abc", 0), "");
});
