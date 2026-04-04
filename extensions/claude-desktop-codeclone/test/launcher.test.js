"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { spawn } = require("node:child_process");
const test = require("node:test");

const {
  BLOCKED_ARGS,
  buildSetupMessage,
  normalizeConfiguredValue,
  parseLauncherArgsJson,
  resolveLaunchSpec,
  validateAdditionalArgs,
  validateConfiguredCommand,
} = require("../src/launcher");

const rootDir = path.resolve(__dirname, "..");
const serverEntry = path.join(rootDir, "server", "index.js");
const echoScript = path.join(__dirname, "fixtures", "echo-stdio.js");

test("normalizeConfiguredValue strips empty and placeholder values", () => {
  assert.equal(normalizeConfiguredValue(""), "");
  assert.equal(normalizeConfiguredValue("  "), "");
  assert.equal(normalizeConfiguredValue("${user_config.launcher_command}"), "");
  assert.equal(normalizeConfiguredValue("codeclone-mcp"), "codeclone-mcp");
});

test("parseLauncherArgsJson accepts a JSON array of strings", () => {
  assert.deepEqual(parseLauncherArgsJson('["--history-limit","4"]'), [
    "--history-limit",
    "4",
  ]);
});

test("parseLauncherArgsJson rejects invalid values", () => {
  assert.throws(() => parseLauncherArgsJson("{"), /JSON array of strings/);
  assert.throws(() => parseLauncherArgsJson("[1]"), /JSON array of strings/);
});

test("validateConfiguredCommand rejects relative paths with separators", () => {
  assert.throws(
    () => validateConfiguredCommand("./codeclone-mcp"),
    /absolute path or a bare command name/,
  );
  assert.doesNotThrow(() => validateConfiguredCommand("codeclone-mcp"));
  assert.doesNotThrow(() => validateConfiguredCommand("/usr/local/bin/codeclone-mcp"));
});

test("validateAdditionalArgs blocks transport reconfiguration", () => {
  assert(BLOCKED_ARGS.has("--transport"));
  assert.throws(
    () => validateAdditionalArgs(["--transport", "streamable-http"]),
    /always uses local stdio transport/,
  );
});

test("resolveLaunchSpec uses explicit launcher config when present", async () => {
  const spec = await resolveLaunchSpec({
    env: {
      CODECLONE_MCP_COMMAND: "/tmp/codeclone-mcp",
      CODECLONE_MCP_ARGS_JSON: '["--history-limit","4"]',
    },
    platform: "darwin",
  });
  assert.deepEqual(spec, {
    command: "/tmp/codeclone-mcp",
    args: ["--history-limit", "4", "--transport", "stdio"],
    source: "configured",
  });
});

test("resolveLaunchSpec falls back to PATH when nothing is configured", async () => {
  const spec = await resolveLaunchSpec({
    env: {
      HOME: "/tmp/codeclone-claude-no-home",
    },
    platform: "linux",
  });
  assert.deepEqual(spec, {
    command: "codeclone-mcp",
    args: ["--transport", "stdio"],
    source: "path",
  });
});

test("buildSetupMessage stays actionable and bounded", () => {
  const text = buildSetupMessage();
  assert.match(text, /uv tool install "codeclone\[mcp\]"/);
  assert.match(text, /absolute launcher path/);
});

test("server proxy launches the configured stdio child", async () => {
  const child = spawn(
    process.execPath,
    [serverEntry],
    {
      cwd: rootDir,
      env: {
        ...process.env,
        CODECLONE_MCP_COMMAND: process.execPath,
        CODECLONE_MCP_ARGS_JSON: JSON.stringify([echoScript]),
      },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );

  const stdoutChunks = [];
  const stderrChunks = [];
  child.stdout.on("data", (chunk) => stdoutChunks.push(String(chunk)));
  child.stderr.on("data", (chunk) => stderrChunks.push(String(chunk)));

  child.stdin.write('{"jsonrpc":"2.0","id":1,"method":"ping"}\n');
  child.stdin.end();

  const exitCode = await new Promise((resolve) => {
    child.on("exit", resolve);
  });

  assert.equal(exitCode, 0);
  assert.equal(stdoutChunks.join(""), '{"jsonrpc":"2.0","id":1,"method":"ping"}\n');
  assert.equal(stderrChunks.join(""), "");
});

test("server proxy prints a setup hint when the launcher is missing", async () => {
  const child = spawn(
    process.execPath,
    [serverEntry],
    {
      cwd: rootDir,
      env: {
        ...process.env,
        CODECLONE_MCP_COMMAND: "/tmp/does-not-exist/codeclone-mcp",
      },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );

  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += String(chunk);
  });
  child.stdin.end();

  const exitCode = await new Promise((resolve) => {
    child.on("exit", resolve);
  });

  assert.equal(exitCode, 2);
  assert.match(stderr, /CodeClone launcher not found/);
});
