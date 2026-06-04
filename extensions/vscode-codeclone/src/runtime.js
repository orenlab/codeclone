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

function toRepoRelativeMcpPath(rootPath, resolvedPath) {
    const root = String(rootPath || "").trim();
    const resolved = String(resolvedPath || "").trim();
    if (!root || !resolved) {
        return null;
    }
    const relative = path.relative(root, resolved);
    if (relative.startsWith("..") || path.isAbsolute(relative)) {
        return null;
    }
    return relative.split(path.sep).join("/");
}

async function resolveCoverageXmlPath(
    rootPath,
    configuredPath = "",
    autoDetect = true,
    exists = pathExists
) {
    const configured = String(configuredPath || "").trim();
    if (configured) {
        const local = workspaceLocalPath(rootPath, configured);
        return local ? toRepoRelativeMcpPath(rootPath, local) : null;
    }
    if (!autoDetect) {
        return null;
    }
    const detected = workspaceLocalPath(rootPath, "coverage.xml");
    if (!detected) {
        return null;
    }
    if (!(await exists(detected))) {
        return null;
    }
    return toRepoRelativeMcpPath(rootPath, detected);
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
    resolveCoverageXmlPath,
    sameGitSnapshot,
};
