"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawn} = require("node:child_process");
const test = require("node:test");

const {
    BLOCKED_ARGS,
    buildSetupMessage,
    exitProxy,
    normalizeConfiguredValue,
    parseLauncherArgsJson,
    resolveLaunchSpec,
    resolvePoetryLauncher,
    validateAdditionalArgs,
    validateConfiguredCommand,
    workspaceLocalLauncherCandidates,
    workspaceRoots,
} = require("../src/launcher");

const rootDir = path.resolve(__dirname, "..");
const serverEntry = path.join(rootDir, "server", "index.js");
const echoScript = path.join(__dirname, "fixtures", "echo-stdio.js");
const hangScript = path.join(__dirname, "fixtures", "hang-stdio.js");

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

test("validateAdditionalArgs blocks the --flag=value bypass form", () => {
    assert.throws(
        () => validateAdditionalArgs(["--transport=streamable-http"]),
        /always uses local stdio transport/,
    );
    assert.throws(
        () => validateAdditionalArgs(["--host=0.0.0.0"]),
        /always uses local stdio transport/,
    );
    assert.throws(
        () => validateAdditionalArgs(["--allow-remote=true"]),
        /always uses local stdio transport/,
    );
});

test("resolveLaunchSpec uses explicit launcher config when present", async () => {
    const spec = await resolveLaunchSpec({
        env: {
            CODECLONE_MCP_COMMAND: "/tmp/codeclone-mcp",
            CODECLONE_MCP_ARGS_JSON: '["--history-limit","4"]',
            CODECLONE_WORKSPACE_ROOT: "/some/project",
        },
        platform: "darwin",
    });
    assert.deepEqual(spec, {
        command: "/tmp/codeclone-mcp",
        args: ["--history-limit", "4", "--transport", "stdio"],
        source: "configured",
        cwd: "/some/project",
    });
});

test("resolveLaunchSpec falls back to PATH when nothing is configured", async () => {
    const emptyWorkspace = fs.mkdtempSync(
        path.join(os.tmpdir(), "codeclone-claude-empty-workspace-"),
    );
    const spec = await resolveLaunchSpec({
        env: {
            HOME: "/tmp/codeclone-claude-no-home",
        },
        platform: "linux",
        cwd: emptyWorkspace,
    });
    assert.deepEqual(spec, {
        command: "codeclone-mcp",
        args: ["--transport", "stdio"],
        source: "path",
        cwd: null,
    });
});

test("workspaceLocalLauncherCandidates prefer workspace virtual environments", () => {
    assert.deepEqual(workspaceLocalLauncherCandidates("/repo", "linux"), [
        "/repo/.venv/bin/codeclone-mcp",
        "/repo/venv/bin/codeclone-mcp",
    ]);
});

test("workspaceRoots places CODECLONE_WORKSPACE_ROOT first, before cwd and PWD", () => {
    const roots = workspaceRoots(
        {CODECLONE_WORKSPACE_ROOT: "/configured", PWD: "/from-pwd"},
        "/from-cwd",
    );
    assert.deepEqual(roots, ["/configured", "/from-cwd", "/from-pwd"]);
});

test("workspaceRoots ignores unset or placeholder CODECLONE_WORKSPACE_ROOT", () => {
    assert.deepEqual(
        workspaceRoots({CODECLONE_WORKSPACE_ROOT: "${user_config.workspace_root}"}, "/cwd"),
        ["/cwd"],
    );
    assert.deepEqual(
        workspaceRoots({CODECLONE_WORKSPACE_ROOT: ""}, "/cwd"),
        ["/cwd"],
    );
    assert.deepEqual(
        workspaceRoots({}, "/cwd"),
        ["/cwd"],
    );
});

test("resolveLaunchSpec prefers a workspace-local launcher before PATH", async () => {
    const workspaceRoot = fs.mkdtempSync(
        path.join(os.tmpdir(), "codeclone-claude-workspace-"),
    );
    const launcherPath = path.join(workspaceRoot, ".venv", "bin", "codeclone-mcp");
    fs.mkdirSync(path.dirname(launcherPath), {recursive: true});
    fs.writeFileSync(launcherPath, "#!/bin/sh\nexit 0\n", "utf8");
    fs.chmodSync(launcherPath, 0o755);

    const spec = await resolveLaunchSpec({
        env: {
            HOME: "/tmp/codeclone-claude-no-home",
        },
        platform: "linux",
        cwd: workspaceRoot,
    });

    assert.deepEqual(spec, {
        command: launcherPath,
        args: ["--transport", "stdio"],
        source: "workspaceLocal",
        cwd: workspaceRoot,
    });
});

test("resolveLaunchSpec walks ancestors of cwd to find a project .venv launcher", async () => {
    const workspaceRoot = fs.mkdtempSync(
        path.join(os.tmpdir(), "codeclone-claude-ancestor-"),
    );
    const launcherPath = path.join(workspaceRoot, ".venv", "bin", "codeclone-mcp");
    fs.mkdirSync(path.dirname(launcherPath), {recursive: true});
    fs.writeFileSync(launcherPath, "#!/bin/sh\nexit 0\n", "utf8");
    fs.chmodSync(launcherPath, 0o755);

    const subdir = path.join(workspaceRoot, "src", "deep", "nested");
    fs.mkdirSync(subdir, {recursive: true});

    const spec = await resolveLaunchSpec({
        env: {
            HOME: "/tmp/codeclone-claude-no-home",
        },
        platform: "linux",
        cwd: subdir,
    });

    assert.deepEqual(spec, {
        command: launcherPath,
        args: ["--transport", "stdio"],
        source: "workspaceLocal",
        cwd: workspaceRoot,
    });
});

test("resolveLaunchSpec uses CODECLONE_WORKSPACE_ROOT even when cwd is wrong", async () => {
    const workspaceRoot = fs.mkdtempSync(
        path.join(os.tmpdir(), "codeclone-claude-wsroot-"),
    );
    const launcherPath = path.join(workspaceRoot, ".venv", "bin", "codeclone-mcp");
    fs.mkdirSync(path.dirname(launcherPath), {recursive: true});
    fs.writeFileSync(launcherPath, "#!/bin/sh\nexit 0\n", "utf8");
    fs.chmodSync(launcherPath, 0o755);

    const spec = await resolveLaunchSpec({
        env: {
            HOME: "/tmp/codeclone-claude-no-home",
            CODECLONE_WORKSPACE_ROOT: workspaceRoot,
        },
        platform: "linux",
        cwd: os.tmpdir(),  // wrong cwd — simulates Claude Desktop launching outside the project
    });

    assert.deepEqual(spec, {
        command: launcherPath,
        args: ["--transport", "stdio"],
        source: "workspaceLocal",
        cwd: workspaceRoot,
    });
});

test("resolvePoetryLauncher finds the launcher inside the active Poetry env", async () => {
    const workspaceRoot = fs.mkdtempSync(
        path.join(os.tmpdir(), "codeclone-claude-poetry-"),
    );
    const toolRoot = fs.mkdtempSync(path.join(os.tmpdir(), "codeclone-claude-tools-"));
    const poetryEnvRoot = path.join(toolRoot, "poetry-env");
    const launcherPath = path.join(poetryEnvRoot, "bin", "codeclone-mcp");
    fs.writeFileSync(path.join(workspaceRoot, "pyproject.toml"), "[tool.poetry]\nname='demo'\n", "utf8");
    fs.mkdirSync(path.dirname(launcherPath), {recursive: true});
    fs.writeFileSync(launcherPath, "#!/bin/sh\nexit 0\n", "utf8");
    fs.chmodSync(launcherPath, 0o755);

    const poetryBin = path.join(toolRoot, "poetry");
    fs.writeFileSync(
        poetryBin,
        "#!/bin/sh\nprintf '%s\\n' \"$FAKE_POETRY_ENV\"\n",
        "utf8",
    );
    fs.chmodSync(poetryBin, 0o755);

    const resolved = await resolvePoetryLauncher(
        {
            ...process.env,
            PATH: toolRoot,
            FAKE_POETRY_ENV: poetryEnvRoot,
        },
        "linux",
        workspaceRoot,
    );

    assert.deepEqual(resolved, {command: launcherPath, root: workspaceRoot});
});

test("buildSetupMessage stays actionable and bounded", () => {
    const text = buildSetupMessage();
    assert.match(text, /workspace, Poetry environment, or PATH/);
    assert.match(text, /absolute launcher path/);
});

test("exitProxy sets exitCode and exits immediately", () => {
    const originalExit = process.exit;
    const originalPause = process.stdin.pause;
    const originalExitCode = process.exitCode;
    /** @type {number | null} */
    let paused = 0;
    /** @type {number | null} */
    let exitArg = null;
    process.stdin.pause = () => {
        paused += 1;
        return process.stdin;
    };
    process.exit = (code) => {
        exitArg = code ?? 0;
        throw new Error("exitProxy sentinel");
    };
    try {
        assert.throws(() => exitProxy(2), /exitProxy sentinel/);
    } finally {
        process.exit = originalExit;
        process.stdin.pause = originalPause;
        process.exitCode = originalExitCode;
    }
    assert.equal(paused, 1);
    assert.equal(exitArg, 2);
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
    assert.match(stderrChunks.join(""), /\[codeclone\] launcher source=configured/);
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

test("server proxy escalates to SIGKILL when the child ignores stdin close and SIGTERM", async () => {
    const child = spawn(
        process.execPath,
        [serverEntry],
        {
            cwd: rootDir,
            env: {
                ...process.env,
                CODECLONE_MCP_COMMAND: process.execPath,
                CODECLONE_MCP_ARGS_JSON: JSON.stringify([hangScript]),
                CODECLONE_MCP_SHUTDOWN_GRACE_MS: "100",
                CODECLONE_MCP_KILL_GRACE_MS: "100",
            },
            stdio: ["pipe", "pipe", "pipe"],
        },
    );

    let stderr = "";
    child.stderr.on("data", (chunk) => {
        stderr += String(chunk);
    });

    // Give the hang-stdio child a beat to register its SIGTERM handler and
    // start its keep-alive interval before we close stdin.
    await new Promise((resolve) => setTimeout(resolve, 50));
    child.stdin.end();

    const {code, signal} = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            child.kill("SIGKILL");
            reject(new Error("wrapper did not escalate to SIGKILL in time"));
        }, 3000);
        child.on("exit", (exitCode, exitSignal) => {
            clearTimeout(timer);
            resolve({code: exitCode, signal: exitSignal});
        });
    });

    // The wrapper should have completed shutdown escalation on its own
    // (SIGTERM → wait → SIGKILL) and reported the terminating signal in
    // its diagnostic stderr. We accept either a non-zero exit code or a
    // signal exit: what matters is that the wrapper did NOT hang.
    assert.ok(
        (typeof code === "number" && code !== 0) || signal,
        `wrapper exited cleanly instead of escalating (code=${code}, signal=${signal})`,
    );
    assert.match(stderr, /Launcher exited via SIGKILL/);
});

test("server proxy exits promptly on launcher startup failure even if stdin stays open", async () => {
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

    const exitCode = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            child.kill("SIGKILL");
            reject(new Error("proxy did not exit promptly"));
        }, 1500);
        child.on("exit", (code) => {
            clearTimeout(timer);
            resolve(code);
        });
    });

    assert.equal(exitCode, 2);
    assert.match(stderr, /CodeClone launcher not found/);
});
