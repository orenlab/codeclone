"use strict";

const {execFile} = require("node:child_process");
const {constants: fsConstants} = require("node:fs");
const fs = require("node:fs/promises");
const path = require("node:path");

function execFilePromise(command, args, options) {
    return new Promise((resolve, reject) => {
        execFile(command, args, options, (error, stdout, stderr) => {
            if (error) {
                reject(error);
                return;
            }
            resolve({stdout, stderr});
        });
    });
}

async function gitStdout(cwd, args) {
    try {
        const result = await execFilePromise("git", args, {
            cwd,
            maxBuffer: 1024 * 1024,
        });
        return String(result.stdout || "").trim();
    } catch {
        return null;
    }
}

async function captureWorkspaceGitSnapshot(folder) {
    const cwd = folder.uri.fsPath;
    const [head, status] = await Promise.all([
        gitStdout(cwd, ["rev-parse", "HEAD"]),
        gitStdout(cwd, ["status", "--porcelain=v1", "--untracked-files=normal"]),
    ]);
    return {
        head,
        dirtySignature: status || "",
    };
}

function sameGitSnapshot(left, right) {
    return (
        (left?.head || null) === (right?.head || null) &&
        (left?.dirtySignature || "") === (right?.dirtySignature || "")
    );
}

async function pathExists(filePath) {
    try {
        await fs.access(filePath);
        return true;
    } catch {
        return false;
    }
}

function workspaceLocalPath(rootPath, candidatePath) {
    const root = String(rootPath || "").trim();
    const candidate = String(candidatePath || "").trim();
    if (!root || !candidate) {
        return null;
    }
    const resolved = path.isAbsolute(candidate)
        ? path.resolve(candidate)
        : path.resolve(root, candidate);
    const relativeToRoot = path.relative(root, resolved);
    if (
        relativeToRoot === "" ||
        (!relativeToRoot.startsWith("..") && !path.isAbsolute(relativeToRoot))
    ) {
        return resolved;
    }
    return null;
}

async function resolveCoverageXmlPath(
    rootPath,
    configuredPath = "",
    autoDetect = true,
    exists = pathExists
) {
    const configured = String(configuredPath || "").trim();
    if (configured) {
        return workspaceLocalPath(rootPath, configured);
    }
    if (!autoDetect) {
        return null;
    }
    const detected = workspaceLocalPath(rootPath, "coverage.xml");
    if (!detected) {
        return null;
    }
    return (await exists(detected)) ? detected : null;
}

const LAUNCHER_NOT_FOUND_MESSAGE =
    "CodeClone launcher not found. Install it outside the workspace " +
    '(uv tool install "codeclone[mcp]") so codeclone-mcp is on PATH, or set ' +
    "codeclone.mcp.command to the absolute path of a trusted launcher. A launcher " +
    "inside the opened workspace (.venv, venv) is never started automatically.";

/**
 * Resolve a bare command name through the absolute entries of PATH only.
 *
 * Opening a workspace is not consent to run programs from it. An empty or
 * relative PATH entry would be resolved against the workspace folder (the
 * launcher's cwd), and a Windows lookup tries the cwd first, so neither is
 * consulted.
 *
 * @param {string} name
 * @param {NodeJS.ProcessEnv} env
 * @param {NodeJS.Platform} platform
 * @returns {Promise<string | null>}
 */
async function resolvePathCommand(name, env = process.env, platform = process.platform) {
    const pathModule = platform === "win32" ? path.win32 : path.posix;
    const executable =
        platform === "win32" && !pathModule.extname(name) ? `${name}.exe` : name;
    const delimiter = platform === "win32" ? ";" : ":";
    for (const entry of String(env.PATH ?? "").split(delimiter)) {
        const directory = entry.trim();
        if (!directory || !pathModule.isAbsolute(directory)) {
            continue;
        }
        const candidate = pathModule.join(directory, executable);
        try {
            const stat = await fs.stat(candidate);
            if (!stat.isFile()) {
                continue;
            }
            if (platform !== "win32") {
                await fs.access(candidate, fsConstants.X_OK);
            }
            return candidate;
        } catch {
            // Not here: keep looking in the next absolute entry.
        }
    }
    return null;
}

/**
 * The launcher the extension may start: the user's configured command, else a
 * codeclone-mcp from an absolute PATH entry. Never a program from the workspace.
 *
 * @param {{
 *   configuredCommand?: string,
 *   configuredArgs?: unknown,
 *   cwd: string,
 *   env?: NodeJS.ProcessEnv,
 *   platform?: NodeJS.Platform,
 * }} options
 */
async function resolveTrustedLaunchSpec(options) {
    const env = options.env ?? process.env;
    const platform = options.platform ?? process.platform;
    const pathModule = platform === "win32" ? path.win32 : path.posix;
    const args = Array.isArray(options.configuredArgs) ? options.configuredArgs : [];
    const configured = String(options.configuredCommand || "").trim();
    if (configured && configured !== "auto") {
        if (/[\\/]/.test(configured) && !pathModule.isAbsolute(configured)) {
            throw new Error(
                "codeclone.mcp.command must be an absolute path or a bare command name; " +
                    "a relative path would be resolved inside the workspace."
            );
        }
        const command = pathModule.isAbsolute(configured)
            ? configured
            : await resolvePathCommand(configured, env, platform);
        if (!command) {
            throw new Error(LAUNCHER_NOT_FOUND_MESSAGE);
        }
        return {command, args, cwd: options.cwd, source: "configured"};
    }
    const command = await resolvePathCommand("codeclone-mcp", env, platform);
    if (!command) {
        throw new Error(LAUNCHER_NOT_FOUND_MESSAGE);
    }
    return {command, args, cwd: options.cwd, source: "path"};
}

async function readFileHead(filePath, maxBytes = 16384) {
    const handle = await fs.open(filePath, "r");
    try {
        const buffer = Buffer.allocUnsafe(maxBytes);
        const {bytesRead} = await handle.read(buffer, 0, maxBytes, 0);
        return buffer.toString("utf8", 0, bytesRead);
    } finally {
        await handle.close();
    }
}

module.exports = {
    LAUNCHER_NOT_FOUND_MESSAGE,
    captureWorkspaceGitSnapshot,
    pathExists,
    readFileHead,
    resolveCoverageXmlPath,
    resolvePathCommand,
    resolveTrustedLaunchSpec,
    sameGitSnapshot,
};
