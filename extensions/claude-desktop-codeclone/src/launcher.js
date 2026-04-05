"use strict";

const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const {spawn} = require("node:child_process");

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
 *   source: string
 * }} LaunchSpec
 */

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
        if (BLOCKED_ARGS.has(arg)) {
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
 * @param {{
 *   env?: NodeJS.ProcessEnv,
 *   platform?: NodeJS.Platform
 * }} [options]
 * @returns {Promise<LaunchSpec>}
 */
async function resolveLaunchSpec(options = {}) {
    const env = options.env ?? process.env;
    const platform = options.platform ?? process.platform;
    const configuredCommand = normalizeConfiguredValue(env.CODECLONE_MCP_COMMAND);
    const configuredArgs = parseLauncherArgsJson(env.CODECLONE_MCP_ARGS_JSON ?? "");
    validateConfiguredCommand(configuredCommand);
    validateAdditionalArgs(configuredArgs);

    if (configuredCommand) {
        return {
            command: configuredCommand,
            args: [...configuredArgs, "--transport", "stdio"],
            source: "configured",
        };
    }

    const autoCommands = await candidateAutoCommands(env, platform);
    if (autoCommands.length > 0) {
        return {
            command: autoCommands[0],
            args: ["--transport", "stdio"],
            source: "auto",
        };
    }

    return {
        command: "codeclone-mcp",
        args: ["--transport", "stdio"],
        source: "path",
    };
}

/**
 * @returns {string}
 */
function buildSetupMessage() {
    return [
        "CodeClone launcher not found.",
        "Install a CodeClone build that includes the MCP extra, or point this bundle at a working codeclone-mcp launcher.",
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
            stream.write(`${prefix}${part}\n`);
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

    /** @type {NodeJS.Signals[]} */
    const signals = ["SIGINT", "SIGTERM", "SIGHUP"];
    const forwardSignal = () => {
        if (!child.killed) {
            child.kill("SIGTERM");
        }
    };
    for (const signal of signals) {
        process.once(signal, forwardSignal);
    }

    process.stdin.on("end", () => {
        child.stdin.end();
    });

    return () => {
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

    const child = spawn(spec.command, spec.args, {
        stdio: ["pipe", "pipe", "pipe"],
        shell: false,
        windowsHide: true,
        env: process.env,
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

    child.on("exit", (code, signal) => {
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
    exitProxy,
    normalizeConfiguredValue,
    parseLauncherArgsJson,
    resolveLaunchSpec,
    runProxy,
    validateAdditionalArgs,
    validateConfiguredCommand,
};
