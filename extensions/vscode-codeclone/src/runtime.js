"use strict";

const {execFile} = require("node:child_process");
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

async function looksLikeCodeCloneRepo(folderPath) {
    const [hasPyproject, hasLegacyServer, hasSurfaceServer] = await Promise.all([
        pathExists(path.join(folderPath, "pyproject.toml")),
        pathExists(path.join(folderPath, "codeclone", "mcp_server.py")),
        pathExists(path.join(folderPath, "codeclone", "surfaces", "mcp", "server.py")),
    ]);
    return hasPyproject && (hasLegacyServer || hasSurfaceServer);
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
    captureWorkspaceGitSnapshot,
    looksLikeCodeCloneRepo,
    pathExists,
    readFileHead,
    sameGitSnapshot,
};
