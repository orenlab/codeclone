"use strict";

const fs = require("node:fs/promises");
const fsSync = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawn, spawnSync} = require("node:child_process");

const USER_CONFIG_PLACEHOLDER_RE = /^\$\{user_config\.[^}]+\}$/;
const BLOCKED_ARGS = new Set([
    "--transport",
    "--host",
    "--port",
    "--allow-remote",
    "--json-response",
    "--stateless-http",
]);

/**
 * @typedef {{
 *   command: string,
 *   args: string[],
 *   source: string,
 *   cwd: string | null
 * }} LaunchSpec
 */

const ANCESTOR_WALK_MAX_DEPTH = 8;

// Bounded escalation on shutdown: after stdin closes or a shutdown signal is
// received, give the child SHUTDOWN_GRACE_MS to exit cleanly; if it is still
// alive, send SIGTERM; if it is still alive KILL_GRACE_MS after that, send
// SIGKILL. Keeps the MCP session from hanging forever when the child wedges.
// Both grace periods can be overridden via env for operator tuning and tests;
// values below 50 ms are clamped to 50 ms to avoid footguns.
const MIN_GRACE_MS = 50;

/**
 * @param {string | undefined} raw
 * @param {number} fallback
 * @returns {number}
 */
function parseGraceMs(raw, fallback) {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || parsed <= 0) {
        return fallback;
    }
    return Math.max(MIN_GRACE_MS, Math.floor(parsed));
}

const SHUTDOWN_GRACE_MS = parseGraceMs(
    process.env.CODECLONE_MCP_SHUTDOWN_GRACE_MS,
    5000,
);
const KILL_GRACE_MS = parseGraceMs(
    process.env.CODECLONE_MCP_KILL_GRACE_MS,
    2000,
);

/**
 * @param {string | undefined} value
 * @returns {string}
 */
function normalizeConfiguredValue(value) {
    const text = String(value ?? "").trim();
    if (!text || USER_CONFIG_PLACEHOLDER_RE.test(text)) {
        return "";
    }
    return text;
}

/**
 * @param {string} value
 * @returns {boolean}
 */
function hasPathSeparator(value) {
    return value.includes("/") || value.includes("\\");
}

/**
 * @param {string} value
 * @returns {string[]}
 */
function parseLauncherArgsJson(value) {
    const text = normalizeConfiguredValue(value);
    if (!text) {
        return [];
    }
    let parsed;
    try {
        parsed = JSON.parse(text);
    } catch (error) {
        throw new Error(
            "Advanced launcher args must be a JSON array of strings.",
            {cause: error},
        );
    }
    if (!Array.isArray(parsed) || parsed.some((item) => typeof item !== "string")) {
        throw new Error("Advanced launcher args must be a JSON array of strings.");
    }
    return parsed.map((item) => item.trim()).filter(Boolean);
}

/**
 * @param {string[]} args
 * @returns {void}
 */
function validateAdditionalArgs(args) {
    for (const arg of args) {
        const head = arg.split("=", 1)[0];
        if (BLOCKED_ARGS.has(head)) {
            throw new Error(
                `Unsupported launcher argument ${arg}. This bundle always uses local stdio transport.`,
            );
        }
    }
}

/**
 * @param {string} command
 * @returns {void}
 */
function validateConfiguredCommand(command) {
    if (!command) {
        return;
    }
    if (hasPathSeparator(command) && !path.isAbsolute(command)) {
        throw new Error(
            "Configured CodeClone launcher must be an absolute path or a bare command name.",
        );
    }
}

/**
 * @param {string} filePath
 * @returns {Promise<boolean>}
 */
async function fileExists(filePath) {
    try {
        await fs.access(filePath);
        return true;
    } catch {
        return false;
    }
}

/**
 * @param {NodeJS.ProcessEnv} env
 * @param {NodeJS.Platform} platform
 * @returns {Promise<string[]>}
 */
async function candidateAutoCommands(env, platform) {
    const executable = platform === "win32" ? "codeclone-mcp.exe" : "codeclone-mcp";
    /** @type {string[]} */
    const candidates = [];
    const home = env.HOME || os.homedir();

    if (platform !== "win32" && home) {
        candidates.push(path.join(home, ".local", "bin", executable));
    }

    if (platform === "darwin" && home) {
        const pythonRoot = path.join(home, "Library", "Python");
        try {
            const entries = await fs.readdir(pythonRoot, {withFileTypes: true});
            for (const entry of entries) {
                if (!entry.isDirectory()) {
                    continue;
                }
                candidates.push(path.join(pythonRoot, entry.name, "bin", executable));
            }
        } catch {
            // No-op: auto-discovery falls back to PATH when local hints do not exist.
        }
    }

    if (platform === "win32") {
        const appData = env.APPDATA;
        const localAppData = env.LOCALAPPDATA;
        if (localAppData) {
            const pythonRoot = path.join(localAppData, "Programs", "Python");
            try {
                const entries = await fs.readdir(pythonRoot, {withFileTypes: true});
                for (const entry of entries) {
                    if (!entry.isDirectory()) {
                        continue;
                    }
                    candidates.push(path.join(pythonRoot, entry.name, "Scripts", executable));
                }
            } catch {
                // No-op: fallback to PATH.
            }
        }
        if (appData) {
            candidates.push(path.join(appData, "Python", "Scripts", executable));
        }
    }

    /** @type {string[]} */
    const existing = [];
    for (const candidate of candidates) {
        if (await fileExists(candidate)) {
            existing.push(candidate);
        }
    }
    return existing;
}

/**
 * @param {string} rootPath
 * @param {NodeJS.Platform} platform
 * @returns {string[]}
 */
function workspaceLocalLauncherCandidates(rootPath, platform) {
    const root = String(rootPath || "").trim();
    if (!root) {
        return [];
    }
    if (platform === "win32") {
        return [
            path.join(root, ".venv", "Scripts", "codeclone-mcp.exe"),
            path.join(root, ".venv", "Scripts", "codeclone-mcp.cmd"),
            path.join(root, "venv", "Scripts", "codeclone-mcp.exe"),
            path.join(root, "venv", "Scripts", "codeclone-mcp.cmd"),
        ];
    }
    return [
        path.join(root, ".venv", "bin", "codeclone-mcp"),
        path.join(root, "venv", "bin", "codeclone-mcp"),
    ];
}

/**
 * @param {NodeJS.ProcessEnv} env
 * @param {string} cwd
 * @returns {string[]}
 */
function workspaceRoots(env, cwd) {
    const configuredRoot = normalizeConfiguredValue(env.CODECLONE_WORKSPACE_ROOT);
    return [
        ...new Set([
            configuredRoot,
            String(cwd || "").trim(),
            String(env.PWD || "").trim(),
        ]),
    ].filter(Boolean);
}

/**
 * Walk upward from a starting directory looking for a workspace-local launcher
 * in an ancestor `.venv`/`venv` virtual environment. Returns the first
 * ancestor directory that contains a matching launcher, or null. Bounded by
 * ANCESTOR_WALK_MAX_DEPTH and by the filesystem root to keep startup cost low
 * and deterministic.
 *
 * @param {string} start
 * @param {NodeJS.Platform} platform
 * @returns {Promise<string | null>}
 */
async function findAncestorWorkspaceRoot(start, platform) {
    const anchor = String(start || "").trim();
    if (!anchor) {
        return null;
    }
    let current = path.resolve(anchor);
    for (let depth = 0; depth < ANCESTOR_WALK_MAX_DEPTH; depth += 1) {
        for (const candidate of workspaceLocalLauncherCandidates(current, platform)) {
            if (await fileExists(candidate)) {
                return current;
            }
        }
        const parent = path.dirname(current);
        if (!parent || parent === current) {
            return null;
        }
        current = parent;
    }
    return null;
}

/**
 * @param {NodeJS.ProcessEnv} env
 * @param {NodeJS.Platform} platform
 * @param {string} cwd
 * @returns {Promise<{command: string, root: string}[]>}
 */
async function candidateWorkspaceCommands(env, platform, cwd) {
    const roots = workspaceRoots(env, cwd);
    const directCandidates = roots.flatMap((root) =>
        workspaceLocalLauncherCandidates(root, platform).map((command) => ({
            command,
            root,
        })),
    );

    /** @type {{command: string, root: string}[]} */
    const existing = [];
    /** @type {Set<string>} */
    const seen = new Set();
    for (const candidate of directCandidates) {
        if (seen.has(candidate.command)) {
            continue;
        }
        if (await fileExists(candidate.command)) {
            existing.push(candidate);
            seen.add(candidate.command);
        }
    }
    if (existing.length > 0) {
        return existing;
    }

    // Ancestor walk only triggers when no direct workspace match is found.
    // This handles the common Claude Desktop case where the bundle is launched
    // from an unrelated cwd but a parent of cwd/PWD is the real project root.
    for (const root of roots) {
        const ancestor = await findAncestorWorkspaceRoot(root, platform);
        if (!ancestor) {
            continue;
        }
        for (const command of workspaceLocalLauncherCandidates(ancestor, platform)) {
            if (seen.has(command)) {
                continue;
            }
            if (await fileExists(command)) {
                existing.push({command, root: ancestor});
                seen.add(command);
            }
        }
    }
    return existing;
}

/**
 * @param {NodeJS.ProcessEnv} env
 * @param {NodeJS.Platform} platform
 * @param {string} cwd
 * @returns {Promise<{command: string, root: string} | null>}
 */
async function resolvePoetryLauncher(env, platform, cwd) {
    const executable = platform === "win32" ? "codeclone-mcp.exe" : "codeclone-mcp";
    for (const root of workspaceRoots(env, cwd)) {
        if (!(await fileExists(path.join(root, "pyproject.toml")))) {
            continue;
        }
        const poetryProbe = spawnSync("poetry", ["env", "info", "-p"], {
            cwd: root,
            env,
            encoding: "utf8",
            stdio: ["ignore", "pipe", "ignore"],
            windowsHide: true,
        });
        const poetryRoot = String(poetryProbe.stdout || "").trim();
        if (!poetryRoot) {
            continue;
        }
        const candidate =
            platform === "win32"
                ? path.join(poetryRoot, "Scripts", executable)
                : path.join(poetryRoot, "bin", executable);
        if (await fileExists(candidate)) {
            return {command: candidate, root};
        }
    }
    return null;
}

/**
 * @param {{
 *   env?: NodeJS.ProcessEnv,
 *   platform?: NodeJS.Platform,
 *   cwd?: string
 * }} [options]
 * @returns {Promise<LaunchSpec>}
 */
async function resolveLaunchSpec(options = {}) {
    const env = options.env ?? process.env;
    const platform = options.platform ?? process.platform;
    const cwd = options.cwd ?? process.cwd();
    const configuredCommand = normalizeConfiguredValue(env.CODECLONE_MCP_COMMAND);
    const configuredArgs = parseLauncherArgsJson(env.CODECLONE_MCP_ARGS_JSON ?? "");
    validateConfiguredCommand(configuredCommand);
    validateAdditionalArgs(configuredArgs);

    const configuredRoot =
        normalizeConfiguredValue(env.CODECLONE_WORKSPACE_ROOT) || null;

    if (configuredCommand) {
        return {
            command: configuredCommand,
            args: [...configuredArgs, "--transport", "stdio"],
            source: "configured",
            cwd: configuredRoot,
        };
    }

    const workspaceCommands = await candidateWorkspaceCommands(env, platform, cwd);
    if (workspaceCommands.length > 0) {
        return {
            command: workspaceCommands[0].command,
            args: ["--transport", "stdio"],
            source: "workspaceLocal",
            cwd: workspaceCommands[0].root,
        };
    }

    const poetryLauncher = await resolvePoetryLauncher(env, platform, cwd);
    if (poetryLauncher) {
        return {
            command: poetryLauncher.command,
            args: ["--transport", "stdio"],
            source: "poetryEnv",
            cwd: poetryLauncher.root,
        };
    }

    const autoCommands = await candidateAutoCommands(env, platform);
    if (autoCommands.length > 0) {
        return {
            command: autoCommands[0],
            args: ["--transport", "stdio"],
            source: "auto",
            cwd: configuredRoot,
        };
    }

    return {
        command: "codeclone-mcp",
        args: ["--transport", "stdio"],
        source: "path",
        cwd: configuredRoot,
    };
}

/**
 * Narrow the TOCTOU window between candidate selection and spawn by re-stating
 * the resolved command and locking onto its realpath. Bare command names
 * (resolved by the OS via PATH) are returned unchanged. Throws on missing or
 * non-regular targets so the caller can surface the setup hint.
 *
 * @param {string} command
 * @returns {string}
 */
function lockResolvedCommand(command) {
    if (!path.isAbsolute(command)) {
        return command;
    }
    const real = fsSync.realpathSync(command);
    const stat = fsSync.statSync(real);
    if (!stat.isFile()) {
        throw Object.assign(new Error(`Resolved launcher is not a regular file: ${real}`), {
            code: "ENOENT",
        });
    }
    return real;
}

/**
 * @returns {string}
 */
function buildSetupMessage() {
    return [
        "CodeClone launcher not found.",
        "Install CodeClone with the MCP extra in the current workspace, Poetry environment, or PATH, or point this bundle at a working codeclone-mcp launcher.",
        "Or configure an absolute launcher path in the Claude Desktop bundle settings.",
    ].join("\n");
}

/**
 * @param {number} code
 * @returns {void}
 */
function exitProxy(code) {
    process.exitCode = code;
    process.stdin.pause();
    process.exit(code);
}

// Strip ANSI escape sequences and other C0/C1 control characters (except tab)
// from child stderr before forwarding. The child is trusted, but its output is
// surfaced to terminals and log viewers that may misrender control bytes.
const CONTROL_CHAR_RE = /\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]|[\x00-\x08\x0b-\x1f\x7f]/g;

/**
 * @param {string} value
 * @returns {string}
 */
function sanitizeForLog(value) {
    return value.replace(CONTROL_CHAR_RE, "");
}

/**
 * @param {NodeJS.WritableStream} stream
 * @param {string} prefix
 * @returns {(chunk: string | Buffer) => void}
 */
function createPrefixedWriter(stream, prefix) {
    let carry = "";
    return (chunk) => {
        const text = carry + String(chunk);
        const parts = text.split(/\r?\n/);
        carry = parts.pop() ?? "";
        for (const part of parts) {
            stream.write(`${prefix}${sanitizeForLog(part)}\n`);
        }
    };
}

/**
 * @param {import("node:child_process").ChildProcessWithoutNullStreams} child
 * @returns {() => void}
 */
function attachChildLifecycle(child) {
    const writeStderr = createPrefixedWriter(process.stderr, "[codeclone] ");
    child.stderr.on("data", writeStderr);
    child.stdout.pipe(process.stdout);
    process.stdin.pipe(child.stdin);

    /** @type {NodeJS.Timeout | null} */
    let sigTermTimer = null;
    /** @type {NodeJS.Timeout | null} */
    let sigKillTimer = null;

    const clearShutdownTimers = () => {
        if (sigTermTimer) {
            clearTimeout(sigTermTimer);
            sigTermTimer = null;
        }
        if (sigKillTimer) {
            clearTimeout(sigKillTimer);
            sigKillTimer = null;
        }
    };

    const childIsAlive = () => child.exitCode === null && child.signalCode === null;

    const scheduleSigKill = () => {
        if (sigKillTimer || !childIsAlive()) {
            return;
        }
        sigKillTimer = setTimeout(() => {
            if (childIsAlive()) {
                try {
                    child.kill("SIGKILL");
                } catch {
                    // Child may have raced to exit; nothing to do.
                }
            }
        }, KILL_GRACE_MS);
        // Do not hold the event loop open on the timer alone.
        if (typeof sigKillTimer.unref === "function") {
            sigKillTimer.unref();
        }
    };

    const sendSigTerm = () => {
        if (!childIsAlive()) {
            return;
        }
        try {
            child.kill("SIGTERM");
        } catch {
            // Child raced to exit before the signal landed.
        }
        scheduleSigKill();
    };

    const scheduleGracefulShutdown = () => {
        if (sigTermTimer || !childIsAlive()) {
            return;
        }
        sigTermTimer = setTimeout(sendSigTerm, SHUTDOWN_GRACE_MS);
        if (typeof sigTermTimer.unref === "function") {
            sigTermTimer.unref();
        }
    };

    /** @type {NodeJS.Signals[]} */
    const signals = ["SIGINT", "SIGTERM", "SIGHUP"];
    const forwardSignal = () => {
        sendSigTerm();
    };
    for (const signal of signals) {
        process.once(signal, forwardSignal);
    }

    process.stdin.on("end", () => {
        if (!child.stdin.destroyed && child.stdin.writable) {
            child.stdin.end();
        }
        scheduleGracefulShutdown();
    });

    return () => {
        clearShutdownTimers();
        child.stdout.unpipe(process.stdout);
        process.stdin.unpipe(child.stdin);
        child.stderr.off("data", writeStderr);
        for (const signal of signals) {
            process.removeListener(signal, forwardSignal);
        }
    };
}

/**
 * @param {{
 *   env?: NodeJS.ProcessEnv,
 *   platform?: NodeJS.Platform
 * }} [options]
 * @returns {Promise<void>}
 */
async function runProxy(options = {}) {
    /** @type {LaunchSpec} */
    let spec;
    try {
        spec = await resolveLaunchSpec(options);
    } catch (error) {
        process.stderr.write(`[codeclone] ${String(error.message || error)}\n`);
        process.exitCode = 2;
        return;
    }

    const spawnCwd = spec.cwd && spec.cwd.length > 0 ? spec.cwd : undefined;
    const childEnv = {...process.env};
    if (spawnCwd && !normalizeConfiguredValue(childEnv.CODECLONE_WORKSPACE_ROOT)) {
        childEnv.CODECLONE_WORKSPACE_ROOT = spawnCwd;
    }

    /** @type {string} */
    let resolvedCommand;
    try {
        resolvedCommand = lockResolvedCommand(spec.command);
    } catch (error) {
        const detail =
            error && typeof error === "object" && "code" in error && error.code === "ENOENT"
                ? buildSetupMessage()
                : String(error.message || error);
        process.stderr.write(`[codeclone] ${sanitizeForLog(detail)}\n`);
        process.exitCode = 2;
        return;
    }

    process.stderr.write(
        `[codeclone] launcher source=${spec.source} command=${resolvedCommand} cwd=${spawnCwd ?? "<inherit>"}\n`,
    );

    const child = spawn(resolvedCommand, spec.args, {
        stdio: ["pipe", "pipe", "pipe"],
        shell: false,
        windowsHide: true,
        env: childEnv,
        cwd: spawnCwd,
    });

    const detach = attachChildLifecycle(child);
    let settled = false;
    const finish = (code) => {
        if (settled) {
            return;
        }
        settled = true;
        detach();
        exitProxy(code);
    };

    child.on("error", (error) => {
        const detail =
            error && typeof error === "object" && "code" in error && error.code === "ENOENT"
                ? buildSetupMessage()
                : String(error.message || error);
        process.stderr.write(`[codeclone] ${detail}\n`);
        finish(2);
    });

    // "close" fires after the child's stdio streams have been fully drained,
    // so any final JSON-RPC response the child wrote right before exiting has
    // already been piped out to our own stdout. Using "exit" here would race
    // with the pipe and silently drop the last response.
    child.on("close", (code, signal) => {
        if (signal) {
            process.stderr.write(`[codeclone] Launcher exited via ${signal}.\n`);
            finish(1);
            return;
        }
        finish(code ?? 1);
    });
}

module.exports = {
    BLOCKED_ARGS,
    buildSetupMessage,
    candidateAutoCommands,
    candidateWorkspaceCommands,
    exitProxy,
    normalizeConfiguredValue,
    parseLauncherArgsJson,
    resolveLaunchSpec,
    resolvePoetryLauncher,
    runProxy,
    validateAdditionalArgs,
    validateConfiguredCommand,
    workspaceLocalLauncherCandidates,
    workspaceRoots,
};
