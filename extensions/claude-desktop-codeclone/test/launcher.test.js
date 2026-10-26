"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawn} = require("node:child_process");
const test = require("node:test");

const launcher = require("../src/launcher");
const {
    BLOCKED_ARGS,
    buildSetupMessage,
    exitProxy,
    normalizeConfiguredValue,
    parseLauncherArgsJson,
    resolveLaunchSpec,
    validateAdditionalArgs,
    validateConfiguredCommand,
} = launcher;

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

/**
 * @param {string} filePath
 * @param {string} marker
 */
function writeMarkerLauncher(filePath, marker) {
    fs.mkdirSync(path.dirname(filePath), {recursive: true});
    fs.writeFileSync(filePath, `#!/bin/sh\nprintf '%s\\n' "$*" >> '${marker}'\n`, "utf8");
    fs.chmodSync(filePath, 0o755);
    return filePath;
}

/**
 * A hostile project that plants a launcher everywhere one used to be found:
 * its .venv and venv, an ancestor's .venv, its root (for a cwd-relative PATH
 * entry) and a Poetry on PATH that reports the project's own .venv.
 */
function hostileWorkspace() {
    const base = fs.mkdtempSync(path.join(os.tmpdir(), "codeclone-claude-hostile-"));
    const root = path.join(base, "parent", "hostile-repo");
    const hostileMarker = path.join(base, "HOSTILE_LAUNCHER_STARTED");
    const trustedMarker = path.join(base, "TRUSTED_LAUNCHER_STARTED");
    for (const planted of [
        path.join(root, ".venv", "bin", "codeclone-mcp"),
        path.join(root, "venv", "bin", "codeclone-mcp"),
        path.join(base, "parent", ".venv", "bin", "codeclone-mcp"),
        path.join(root, "codeclone-mcp"),
    ]) {
        writeMarkerLauncher(planted, hostileMarker);
    }
    fs.writeFileSync(path.join(root, "pyproject.toml"), "[tool.poetry]\nname='x'\n", "utf8");
    const tools = path.join(base, "tools-bin");
    fs.mkdirSync(tools, {recursive: true});
    fs.writeFileSync(
        path.join(tools, "poetry"),
        `#!/bin/sh\nprintf '%s\\n' '${path.join(root, ".venv")}'\n`,
        "utf8",
    );
    fs.chmodSync(path.join(tools, "poetry"), 0o755);
    const trustedDir = path.join(base, "trusted-install", "bin");
    const trusted = writeMarkerLauncher(path.join(trustedDir, "codeclone-mcp"), trustedMarker);
    const home = path.join(base, "home");
    fs.mkdirSync(home, {recursive: true});
    return {base, root, hostileMarker, trustedMarker, tools, trustedDir, trusted, home};
}

/**
 * Run the bundle's real entry point from inside the workspace.
 *
 * @param {{root: string, home: string}} workspace
 * @param {Record<string, string>} env
 * @returns {Promise<{code: number | null, stderr: string}>}
 */
async function runServerIn(workspace, env) {
    const child = spawn(process.execPath, [serverEntry], {
        cwd: workspace.root,
        env: {HOME: workspace.home, PWD: workspace.root, ...env},
        stdio: ["pipe", "pipe", "pipe"],
    });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
        stderr += String(chunk);
    });
    child.stdin.end();
    const code = await new Promise((resolve) => {
        child.on("exit", resolve);
    });
    return {code, stderr};
}

test("the bundle never starts a launcher planted in the opened workspace", async () => {
    const workspace = hostileWorkspace();

    const {code, stderr} = await runServerIn(workspace, {
        PATH: [workspace.tools, ".", ""].join(path.delimiter),
        CODECLONE_WORKSPACE_ROOT: workspace.root,
    });

    assert.equal(fs.existsSync(workspace.hostileMarker), false, stderr);
    assert.equal(code, 2, stderr);
    assert.match(stderr, /CodeClone launcher not found/);
});

test("the bundle starts the trusted install outside the workspace", async () => {
    const workspace = hostileWorkspace();

    const {code, stderr} = await runServerIn(workspace, {
        PATH: [workspace.tools, workspace.trustedDir].join(path.delimiter),
        CODECLONE_WORKSPACE_ROOT: workspace.root,
    });

    assert.equal(fs.existsSync(workspace.hostileMarker), false, stderr);
    assert.equal(code, 0, stderr);
    assert.equal(fs.readFileSync(workspace.trustedMarker, "utf8"), "--transport stdio\n");
    assert.match(stderr, /launcher source=path/);
});

test("the bundle skips relative PATH entries before a trusted one", async () => {
    const workspace = hostileWorkspace();
    for (const dir of [".venv", "venv"]) {
        fs.rmSync(path.join(workspace.root, dir), {recursive: true, force: true});
    }
    fs.rmSync(path.join(workspace.base, "parent", ".venv"), {recursive: true, force: true});

    const {code, stderr} = await runServerIn(workspace, {
        PATH: [".", "", workspace.trustedDir].join(path.delimiter),
        CODECLONE_WORKSPACE_ROOT: workspace.root,
    });

    assert.equal(fs.existsSync(workspace.hostileMarker), false, stderr);
    assert.equal(code, 0, stderr);
    assert.equal(fs.existsSync(workspace.trustedMarker), true);
});

test("a configured bare command name is resolved through absolute PATH entries only", async () => {
    const workspace = hostileWorkspace();

    const {code, stderr} = await runServerIn(workspace, {
        PATH: [".", workspace.trustedDir].join(path.delimiter),
        CODECLONE_MCP_COMMAND: "codeclone-mcp",
        CODECLONE_WORKSPACE_ROOT: workspace.root,
    });

    assert.equal(fs.existsSync(workspace.hostileMarker), false, stderr);
    assert.equal(code, 0, stderr);
    assert.equal(fs.existsSync(workspace.trustedMarker), true);
    assert.match(stderr, /launcher source=configured/);
});

test("the configured absolute launcher is started", async () => {
    const workspace = hostileWorkspace();

    const {code, stderr} = await runServerIn(workspace, {
        PATH: workspace.tools,
        CODECLONE_MCP_COMMAND: workspace.trusted,
        CODECLONE_WORKSPACE_ROOT: workspace.root,
    });

    assert.equal(fs.existsSync(workspace.hostileMarker), false, stderr);
    assert.equal(code, 0, stderr);
    assert.equal(fs.existsSync(workspace.trustedMarker), true);
});

test("resolveLaunchSpec resolves PATH to an absolute launcher outside the workspace", async () => {
    const workspace = hostileWorkspace();

    const spec = await resolveLaunchSpec({
        env: {HOME: workspace.home, PATH: [".", workspace.trustedDir].join(path.delimiter)},
        platform: "linux",
        cwd: workspace.root,
    });

    assert.deepEqual(spec, {
        command: workspace.trusted,
        args: ["--transport", "stdio"],
        source: "path",
        cwd: null,
    });
});

test("resolvePathCommand ignores relative entries and non-executable files", async () => {
    const workspace = hostileWorkspace();
    const plain = path.join(workspace.base, "plain-bin");
    fs.mkdirSync(plain, {recursive: true});
    fs.writeFileSync(path.join(plain, "codeclone-mcp"), "", "utf8");

    assert.equal(
        await launcher.resolvePathCommand(
            "codeclone-mcp",
            {PATH: [".", "", plain].join(":")},
            "linux",
        ),
        null,
    );
    assert.equal(
        await launcher.resolvePathCommand(
            "codeclone-mcp",
            {PATH: [plain, workspace.trustedDir].join(":")},
            "linux",
        ),
        workspace.trusted,
    );
});

test("buildSetupMessage stays actionable and bounded", () => {
    const text = buildSetupMessage();
    assert.match(text, /uv tool install "codeclone\[mcp\]"/);
    assert.match(text, /absolute launcher path/);
    assert.match(text, /never started automatically/);
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
