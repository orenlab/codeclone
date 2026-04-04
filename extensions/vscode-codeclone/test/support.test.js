"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  ANALYSIS_PROFILE_CUSTOM,
  ANALYSIS_PROFILE_DEEPER_REVIEW,
  ANALYSIS_PROFILE_DEFAULTS,
  DEFAULT_ANALYSIS_THRESHOLDS,
  DEEP_REVIEW_ANALYSIS_THRESHOLDS,
  STALE_REASON_EDITOR,
  STALE_REASON_WORKSPACE,
  analysisThresholdOverrides,
  customAnalysisThresholds,
  normalizedLaunchSpec,
  normalizeAnalysisProfile,
  parseUtcTimestamp,
  resolveWorkspacePath,
  resolveAnalysisSettings,
  sameAnalysisSettings,
  signedInteger,
  staleMessage,
  trimTail,
  workspaceLocalLauncherCandidates,
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

test("workspaceLocalLauncherCandidates prefer workspace virtual environments", () => {
  assert.deepEqual(workspaceLocalLauncherCandidates("/workspace/repo", "linux"), [
    "/workspace/repo/.venv/bin/codeclone-mcp",
    "/workspace/repo/venv/bin/codeclone-mcp",
  ]);
  assert.deepEqual(workspaceLocalLauncherCandidates("C:\\repo", "win32"), [
    "C:\\repo\\.venv\\Scripts\\codeclone-mcp.exe",
    "C:\\repo\\.venv\\Scripts\\codeclone-mcp.cmd",
    "C:\\repo\\venv\\Scripts\\codeclone-mcp.exe",
    "C:\\repo\\venv\\Scripts\\codeclone-mcp.cmd",
  ]);
});

test("normalizeAnalysisProfile falls back to conservative defaults", () => {
  assert.equal(normalizeAnalysisProfile("defaults"), ANALYSIS_PROFILE_DEFAULTS);
  assert.equal(
    normalizeAnalysisProfile("deeperReview"),
    ANALYSIS_PROFILE_DEEPER_REVIEW
  );
  assert.equal(normalizeAnalysisProfile("custom"), ANALYSIS_PROFILE_CUSTOM);
  assert.equal(normalizeAnalysisProfile("unknown"), ANALYSIS_PROFILE_DEFAULTS);
});

test("customAnalysisThresholds normalizes values to non-negative integers", () => {
  assert.deepEqual(
    customAnalysisThresholds({
      minLoc: "5",
      minStmt: 2.7,
      blockMinLoc: -4,
      blockMinStmt: "bad",
      segmentMinLoc: 0,
      segmentMinStmt: 3,
    }),
    {
      minLoc: 5,
      minStmt: 2,
      blockMinLoc: DEFAULT_ANALYSIS_THRESHOLDS.blockMinLoc,
      blockMinStmt: DEFAULT_ANALYSIS_THRESHOLDS.blockMinStmt,
      segmentMinLoc: 0,
      segmentMinStmt: 3,
    }
  );
});

test("resolveAnalysisSettings keeps defaults conservative and deeper review explicit", () => {
  assert.deepEqual(resolveAnalysisSettings({}), {
    profileId: ANALYSIS_PROFILE_DEFAULTS,
    label: "Conservative",
    detail: "Use repo defaults or pyproject for the first pass.",
    thresholds: DEFAULT_ANALYSIS_THRESHOLDS,
    thresholdSummary: "Repo defaults / pyproject",
    overrides: {},
  });
  assert.deepEqual(resolveAnalysisSettings({ profile: "deeperReview" }), {
    profileId: ANALYSIS_PROFILE_DEEPER_REVIEW,
    label: "Deeper review",
    detail: "Lower thresholds for a deliberate second pass on smaller units.",
    thresholds: DEEP_REVIEW_ANALYSIS_THRESHOLDS,
    thresholdSummary: "5/2 across functions, blocks, and segments",
    overrides: analysisThresholdOverrides(DEEP_REVIEW_ANALYSIS_THRESHOLDS),
  });
});

test("resolveAnalysisSettings uses workspace thresholds in custom mode", () => {
  const custom = resolveAnalysisSettings({
    profile: "custom",
    minLoc: 7,
    minStmt: 3,
    blockMinLoc: 11,
    blockMinStmt: 4,
    segmentMinLoc: 13,
    segmentMinStmt: 5,
  });
  assert.deepEqual(custom.thresholds, {
    minLoc: 7,
    minStmt: 3,
    blockMinLoc: 11,
    blockMinStmt: 4,
    segmentMinLoc: 13,
    segmentMinStmt: 5,
  });
  assert.equal(custom.thresholdSummary, "func 7/3 · block 11/4 · seg 13/5");
});

test("sameAnalysisSettings compares profile payloads structurally", () => {
  const left = resolveAnalysisSettings({ profile: "custom", minLoc: 8 });
  const right = resolveAnalysisSettings({ profile: "custom", minLoc: 8 });
  const other = resolveAnalysisSettings({ profile: "deeperReview" });
  assert.equal(sameAnalysisSettings(left, right), true);
  assert.equal(sameAnalysisSettings(left, other), false);
});
