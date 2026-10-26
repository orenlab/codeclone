"use strict";

// Drives the real extension.js connect path (activate -> connectMcp ->
// ensureConnected -> resolveLaunchSpec -> MCP client spawn) against a stubbed
// `vscode` module, so the launcher the extension actually starts is observed
// by marker files, without a VS Code extension host.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const Module = require("node:module");

/** A value that answers every property access, call and construction. */
function deepStub(overrides = {}) {
    const cache = new Map(Object.entries(overrides));
    const target = function stub() {};
    return new Proxy(target, {
        get(_target, prop) {
            if (prop === "then") {
                return undefined;
            }
            if (prop === Symbol.iterator) {
                return function* empty() {};
            }
            if (prop === Symbol.toPrimitive) {
                return () => "";
            }
            if (!cache.has(prop)) {
                cache.set(prop, deepStub());
            }
            return cache.get(prop);
        },
        set(_target, prop, value) {
            cache.set(prop, value);
            return true;
        },
        apply() {
            return deepStub();
        },
        construct() {
            return deepStub();
        },
    });
}

/** @type {Map<string, Function>} */
const commands = new Map();

const resolved = async () => undefined;
const vscodeStub = deepStub({
    workspace: deepStub({
        isTrusted: true,
        workspaceFolders: [],
        getConfiguration: () => ({get: (_key, fallback) => fallback}),
    }),
    window: deepStub({
        activeTextEditor: undefined,
        withProgress: (_options, task) => task(deepStub()),
        showInformationMessage: resolved,
        showErrorMessage: resolved,
        showWarningMessage: resolved,
    }),
    commands: deepStub({
        registerCommand: (name, callback) => {
            commands.set(name, callback);
            return deepStub();
        },
        executeCommand: resolved,
    }),
});

const moduleInternals = /** @type {{_load: Function}} */ (/** @type {unknown} */ (Module));
const originalLoad = moduleInternals._load;
moduleInternals._load = function patchedLoad(request, parent, isMain) {
    if (request === "vscode") {
        return vscodeStub;
    }
    return originalLoad.call(this, request, parent, isMain);
};

const extension = require("../src/extension");

/**
 * @param {string} filePath
 * @param {string} marker
 */
function writeMarkerLauncher(filePath, marker) {
    fs.mkdirSync(path.dirname(filePath), {recursive: true});
    // Stays alive on stdin like a server would, so the client's handshake
    // write does not race a process that already exited.
    fs.writeFileSync(
        filePath,
        `#!/bin/sh\nprintf '%s\\n' "$*" >> '${marker}'\nexec /bin/cat > /dev/null\n`,
        "utf8"
    );
    fs.chmodSync(filePath, 0o755);
    return filePath;
}

function hostileWorkspace() {
    const base = fs.mkdtempSync(path.join(os.tmpdir(), "codeclone-vscode-wiring-"));
    const root = path.join(base, "hostile-repo");
    const hostileMarker = path.join(base, "HOSTILE_LAUNCHER_STARTED");
    const trustedMarker = path.join(base, "TRUSTED_LAUNCHER_STARTED");
    for (const planted of [
        path.join(root, ".venv", "bin", "codeclone-mcp"),
        path.join(root, "venv", "bin", "codeclone-mcp"),
        path.join(root, "codeclone-mcp"),
    ]) {
        writeMarkerLauncher(planted, hostileMarker);
    }
    const trustedDir = path.join(base, "trusted-install", "bin");
    writeMarkerLauncher(path.join(trustedDir, "codeclone-mcp"), trustedMarker);
    return {root, hostileMarker, trustedMarker, trustedDir};
}

/**
 * @param {{root: string}} workspace
 * @param {string} pathValue
 */
async function connectFrom(workspace, pathValue) {
    const savedPath = process.env.PATH;
    process.env.PATH = pathValue;
    vscodeStub.workspace.workspaceFolders = [
        {
            uri: {fsPath: workspace.root, toString: () => `file://${workspace.root}`},
            name: "hostile-repo",
            index: 0,
        },
    ];
    commands.clear();
    extension.activate(deepStub({subscriptions: [], workspaceState: deepStub({get: (_k, d) => d, update: resolved})}));
    try {
        await Promise.race([
            commands.get("codeclone.connectMcp")(),
            new Promise((resolve) => setTimeout(resolve, 3000)),
        ]);
    } finally {
        process.env.PATH = savedPath;
        await extension.deactivate().catch(() => undefined);
    }
}

test("connecting from a hostile workspace starts no program from it", async () => {
    const workspace = hostileWorkspace();

    await connectFrom(workspace, [".", ""].join(path.delimiter));

    assert.equal(fs.existsSync(workspace.hostileMarker), false);
});

test("connecting starts the trusted install outside the workspace", async () => {
    const workspace = hostileWorkspace();

    await connectFrom(workspace, [".", workspace.trustedDir].join(path.delimiter));

    assert.equal(fs.existsSync(workspace.hostileMarker), false);
    // The extension passes no arguments of its own: stdio is the server default.
    assert.equal(fs.readFileSync(workspace.trustedMarker, "utf8"), "\n");
});
