"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {looksLikeCodeCloneRepo} = require("../src/runtime");

test("looksLikeCodeCloneRepo accepts the current MCP surface layout", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "codeclone-vscode-runtime-"));
    fs.writeFileSync(path.join(root, "pyproject.toml"), "[project]\nname='codeclone'\n");
    fs.mkdirSync(path.join(root, "codeclone", "surfaces", "mcp"), {recursive: true});
    fs.writeFileSync(
        path.join(root, "codeclone", "surfaces", "mcp", "server.py"),
        "# marker\n"
    );

    await assert.doesNotReject(async () => {
        assert.equal(await looksLikeCodeCloneRepo(root), true);
    });
});

test("looksLikeCodeCloneRepo still accepts the legacy MCP server path", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "codeclone-vscode-runtime-"));
    fs.writeFileSync(path.join(root, "pyproject.toml"), "[project]\nname='codeclone'\n");
    fs.mkdirSync(path.join(root, "codeclone"), {recursive: true});
    fs.writeFileSync(path.join(root, "codeclone", "mcp_server.py"), "# legacy marker\n");

    await assert.doesNotReject(async () => {
        assert.equal(await looksLikeCodeCloneRepo(root), true);
    });
});

test("looksLikeCodeCloneRepo rejects non-CodeClone workspaces", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "codeclone-vscode-runtime-"));
    fs.writeFileSync(path.join(root, "pyproject.toml"), "[project]\nname='other'\n");

    await assert.doesNotReject(async () => {
        assert.equal(await looksLikeCodeCloneRepo(root), false);
    });
});
