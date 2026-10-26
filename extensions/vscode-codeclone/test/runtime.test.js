"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const runtime = require("../src/runtime");
const {resolveCoverageXmlPath} = runtime;
const {CodeCloneMcpClient} = require("../src/mcpClient");

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
 * A hostile workspace with a launcher planted where one used to be found
 * (.venv, venv, the folder itself for a relative PATH entry) and a folder that
 * looks like the CodeClone repository (the old `uv run` fallback).
 */
function hostileWorkspace() {
    const base = fs.mkdtempSync(path.join(os.tmpdir(), "codeclone-vscode-hostile-"));
    const root = path.join(base, "hostile-repo");
    const hostileMarker = path.join(base, "HOSTILE_LAUNCHER_STARTED");
    const trustedMarker = path.join(base, "TRUSTED_LAUNCHER_STARTED");
    for (const planted of [
        path.join(root, ".venv", "bin", "codeclone-mcp"),
        path.join(root, "venv", "bin", "codeclone-mcp"),
        path.join(root, "codeclone-mcp"),
        path.join(root, "uv"),
    ]) {
        writeMarkerLauncher(planted, hostileMarker);
    }
    fs.writeFileSync(path.join(root, "pyproject.toml"), "[project]\nname='codeclone'\n");
    fs.mkdirSync(path.join(root, "codeclone", "surfaces", "mcp"), {recursive: true});
    fs.writeFileSync(path.join(root, "codeclone", "surfaces", "mcp", "server.py"), "#\n");
    const trustedDir = path.join(base, "trusted-install", "bin");
    const trusted = writeMarkerLauncher(path.join(trustedDir, "codeclone-mcp"), trustedMarker);
    return {base, root, hostileMarker, trustedMarker, trustedDir, trusted};
}

/**
 * Start the resolved launcher exactly as the extension's MCP client does.
 *
 * @param {{command: string, args: string[], cwd: string}} spec
 */
async function startAsTheClientDoes(spec) {
    const client = new CodeCloneMcpClient(null);
    await client._spawn(spec);
    await new Promise((resolve) => {
        if (client.process.exitCode !== null) {
            resolve(undefined);
            return;
        }
        client.process.once("exit", resolve);
    });
}

test("the extension never starts a launcher planted in the workspace", async () => {
    const workspace = hostileWorkspace();

    await assert.rejects(
        runtime.resolveTrustedLaunchSpec({
            configuredCommand: "auto",
            configuredArgs: [],
            cwd: workspace.root,
            env: {PATH: [".", ""].join(":")},
            platform: "linux",
        }),
        /CodeClone launcher not found/
    );
    assert.equal(fs.existsSync(workspace.hostileMarker), false);
});

test("the extension starts the trusted install outside the workspace", async () => {
    const workspace = hostileWorkspace();

    const spec = await runtime.resolveTrustedLaunchSpec({
        configuredCommand: "auto",
        configuredArgs: [],
        cwd: workspace.root,
        env: {PATH: [".", "", workspace.trustedDir].join(":")},
        platform: "linux",
    });
    await startAsTheClientDoes(spec);

    assert.deepEqual(spec, {
        command: workspace.trusted,
        args: [],
        cwd: workspace.root,
        source: "path",
    });
    assert.equal(fs.existsSync(workspace.hostileMarker), false);
    assert.equal(fs.readFileSync(workspace.trustedMarker, "utf8"), "\n");
});

test("a configured bare command is resolved through absolute PATH entries only", async () => {
    const workspace = hostileWorkspace();

    const spec = await runtime.resolveTrustedLaunchSpec({
        configuredCommand: "codeclone-mcp",
        configuredArgs: ["--history-limit", "4"],
        cwd: workspace.root,
        env: {PATH: [".", workspace.trustedDir].join(":")},
        platform: "linux",
    });

    assert.equal(spec.command, workspace.trusted);
    assert.equal(spec.source, "configured");
    assert.deepEqual(spec.args, ["--history-limit", "4"]);
});

test("a configured relative launcher path is refused", async () => {
    const workspace = hostileWorkspace();

    await assert.rejects(
        runtime.resolveTrustedLaunchSpec({
            configuredCommand: ".venv/bin/codeclone-mcp",
            configuredArgs: [],
            cwd: workspace.root,
            env: {PATH: workspace.trustedDir},
            platform: "linux",
        }),
        /must be an absolute path or a bare command name/
    );
});

test("a configured absolute launcher is used as given", async () => {
    const workspace = hostileWorkspace();

    const spec = await runtime.resolveTrustedLaunchSpec({
        configuredCommand: workspace.trusted,
        configuredArgs: [],
        cwd: workspace.root,
        env: {PATH: ""},
        platform: "linux",
    });

    assert.equal(spec.command, workspace.trusted);
    assert.equal(spec.source, "configured");
});

test("resolvePathCommand ignores relative entries and non-executable files", async () => {
    const workspace = hostileWorkspace();
    const plain = path.join(workspace.base, "plain-bin");
    fs.mkdirSync(plain, {recursive: true});
    fs.writeFileSync(path.join(plain, "codeclone-mcp"), "", "utf8");

    assert.equal(
        await runtime.resolvePathCommand("codeclone-mcp", {PATH: `.::${plain}`}, "linux"),
        null
    );
    assert.equal(
        await runtime.resolvePathCommand(
            "codeclone-mcp",
            {PATH: `${plain}:${workspace.trustedDir}`},
            "linux"
        ),
        workspace.trusted
    );
});

test("relative PATH entries never resolve into the current directory", async () => {
    // Run from inside the hostile workspace: a relative entry would find its
    // planted launcher and hand back a bare name the spawn then resolves there.
    const workspace = hostileWorkspace();
    const saved = process.cwd();
    process.chdir(workspace.root);
    try {
        assert.equal(
            await runtime.resolvePathCommand("codeclone-mcp", {PATH: ".::./"}, "linux"),
            null
        );
    } finally {
        process.chdir(saved);
    }
});

test("resolveCoverageXmlPath keeps coverage input workspace-local and auto-detectable", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "codeclone-vscode-runtime-"));
    const coverageXml = path.join(root, "coverage.xml");
    fs.writeFileSync(coverageXml, "<coverage />\n");

    assert.equal(await resolveCoverageXmlPath(root, "", true), coverageXml);
    assert.equal(
        await resolveCoverageXmlPath(root, "reports/coverage.xml", true, async () => false),
        path.join(root, "reports", "coverage.xml")
    );
    assert.equal(await resolveCoverageXmlPath(root, "", false), null);
    assert.equal(await resolveCoverageXmlPath(root, "../coverage.xml", true), null);
});
