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
