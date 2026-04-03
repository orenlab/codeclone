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
