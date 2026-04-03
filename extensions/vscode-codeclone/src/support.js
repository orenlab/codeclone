"use strict";

const path = require("node:path");

const STALE_REASON_EDITOR = "unsaved editor changes";
const STALE_REASON_WORKSPACE = "workspace changed after this run";

function signedInteger(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "0";
  }
  return value > 0 ? `+${value}` : String(value);
}

function parseUtcTimestamp(value) {
  if (!value) {
    return null;
  }
  const parsed = Date.parse(String(value));
  return Number.isNaN(parsed) ? null : parsed;
}

function staleMessage(reason) {
  if (reason === STALE_REASON_EDITOR) {
    return "Review data may be stale because there are unsaved editor changes.";
  }
  return "Review data may be stale because the workspace changed after this run.";
}

function normalizedLaunchSpec(spec) {
  const command = String(spec?.command || "").trim();
  if (!command) {
    throw new Error("CodeClone MCP launcher command must not be empty.");
  }
  const args = Array.isArray(spec?.args)
    ? spec.args
        .filter((value) => typeof value === "string")
        .map((value) => value.trim())
        .filter(Boolean)
    : [];
  const cwd = String(spec?.cwd || "").trim();
  if (!cwd) {
    throw new Error("CodeClone MCP launcher cwd must not be empty.");
  }
  return { command, args, cwd };
}

function trimTail(value, maxChars) {
  const text = String(value || "");
  if (!Number.isFinite(maxChars) || maxChars < 1) {
    return "";
  }
  return text.length <= maxChars ? text : text.slice(-maxChars);
}

function resolveWorkspacePath(rootPath, relativePath) {
  const root = String(rootPath || "").trim();
  const candidate = String(relativePath || "").trim();
  if (!root || !candidate) {
    return null;
  }
  const resolved = path.resolve(root, candidate);
  const relativeToRoot = path.relative(root, resolved);
  if (
    relativeToRoot === "" ||
    (!relativeToRoot.startsWith("..") && !path.isAbsolute(relativeToRoot))
  ) {
    return resolved;
  }
  return null;
}

function workspaceLocalLauncherCandidates(
  rootPath,
  platform = process.platform
) {
  const root = String(rootPath || "").trim();
  if (!root) {
    return [];
  }
  const platformPath = platform === "win32" ? path.win32 : path.posix;
  if (platform === "win32") {
    return [
      platformPath.join(root, ".venv", "Scripts", "codeclone-mcp.exe"),
      platformPath.join(root, ".venv", "Scripts", "codeclone-mcp.cmd"),
      platformPath.join(root, "venv", "Scripts", "codeclone-mcp.exe"),
      platformPath.join(root, "venv", "Scripts", "codeclone-mcp.cmd"),
    ];
  }
  return [
    platformPath.join(root, ".venv", "bin", "codeclone-mcp"),
    platformPath.join(root, "venv", "bin", "codeclone-mcp"),
  ];
}

module.exports = {
  STALE_REASON_EDITOR,
  STALE_REASON_WORKSPACE,
  normalizedLaunchSpec,
  parseUtcTimestamp,
  resolveWorkspacePath,
  signedInteger,
  staleMessage,
  trimTail,
  workspaceLocalLauncherCandidates,
};
