"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

function loadPackageJson() {
    const filePath = path.resolve(__dirname, "..", "package.json");
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

test("every menu command is declared in contributes.commands", () => {
    const pkg = loadPackageJson();
    const declaredCommands = new Set(
        pkg.contributes.commands.map((entry) => entry.command)
    );
    const missing = [];

    for (const items of Object.values(pkg.contributes.menus)) {
        for (const entry of items) {
            if (!declaredCommands.has(entry.command)) {
                missing.push(entry.command);
            }
        }
    }

    assert.deepEqual(missing, []);
});

test("every CodeClone view declares an icon for moved-view scenarios", () => {
    const pkg = loadPackageJson();
    const views = pkg.contributes.views.codeclone;

    assert.equal(Array.isArray(views), true);
    for (const view of views) {
        assert.equal(typeof view.icon, "string");
        assert.notEqual(view.icon.trim(), "");
    }
});

test("editor toolbar keeps a single primary action", () => {
    const pkg = loadPackageJson();
    const editorTitle = pkg.contributes.menus["editor/title"];
    const primaryActions = editorTitle.filter((entry) =>
        String(entry.group || "").startsWith("navigation")
    );

    assert.equal(primaryActions.length, 1);
});

test("primary user-facing command titles stay verb-first", () => {
    const pkg = loadPackageJson();
    const commands = new Map(
        pkg.contributes.commands.map((entry) => [entry.command, entry.title])
    );

    assert.equal(commands.get("codeclone.setAnalysisProfile"), "Set Analysis Depth");
    assert.equal(commands.get("codeclone.openSetupHelp"), "Open Setup Help");
});

test("configuration settings declare explicit scopes that match their usage", () => {
    const pkg = loadPackageJson();
    const properties = pkg.contributes.configuration.properties;

    assert.equal(properties["codeclone.mcp.command"].scope, "machine");
    assert.equal(properties["codeclone.mcp.args"].scope, "machine");
    assert.equal(properties["codeclone.analysis.changedDiffRef"].scope, "resource");
    assert.equal(properties["codeclone.analysis.coverageXml"].scope, "resource");
    assert.equal(
        properties["codeclone.analysis.autoDetectCoverageXml"].scope,
        "resource"
    );
    assert.equal(properties["codeclone.analysis.profile"].scope, "resource");
    assert.equal(properties["codeclone.analysis.minLoc"].scope, "resource");
    assert.equal(properties["codeclone.analysis.minStmt"].scope, "resource");
    assert.equal(properties["codeclone.analysis.blockMinLoc"].scope, "resource");
    assert.equal(properties["codeclone.analysis.blockMinStmt"].scope, "resource");
    assert.equal(properties["codeclone.analysis.segmentMinLoc"].scope, "resource");
    assert.equal(properties["codeclone.analysis.segmentMinStmt"].scope, "resource");
    assert.equal(properties["codeclone.ui.showStatusBar"].scope, "window");
});

// Ratchet: CodeClone 2.1.0a2 withdrew the per-call cache controls (cache_policy,
// cache_path, max_cache_size_mb) -- managing the physical cache backend is operator
// configuration, and the MCP server now refuses those arguments on every tool.
//
// The defect this forbids: a workspace setting the server refuses is worse than no
// setting at all. Each tool's argument model is built from its handler signature and
// pydantic ignores unknown keys, so to a client that still sends the value, "silently
// dropped" is indistinguishable from "honoured" -- the call succeeds and the value goes
// nowhere. Declaring one here puts that dead control in the VS Code settings UI, where
// it is shown, persisted per-resource, and read by nothing.
//
// Re-wiring is not the fix. The control was withdrawn deliberately as a breaking change;
// restoring a per-workspace cache policy would reverse it.
test("no withdrawn cache control is offered as a workspace setting", () => {
    const pkg = loadPackageJson();
    const declared = Object.keys(pkg.contributes.configuration.properties);
    const withdrawn = /(^|\.)(cachePolicy|cachePath|maxCacheSizeMb|cache_policy|cache_path|max_cache_size_mb)$/;

    const offered = declared.filter((name) => withdrawn.test(name));

    assert.deepEqual(
        offered,
        [],
        `VS Code declares withdrawn cache control(s) the MCP server refuses: ${offered.join(", ")}`
    );
});
