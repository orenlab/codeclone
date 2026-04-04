"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const rootDir = path.resolve(__dirname, "..");
const manifest = JSON.parse(
  fs.readFileSync(path.join(rootDir, "manifest.json"), "utf8"),
);
const packageJson = JSON.parse(
  fs.readFileSync(path.join(rootDir, "package.json"), "utf8"),
);

test("manifest and package metadata stay aligned", () => {
  assert.equal(manifest.version, packageJson.version);
  assert.equal(manifest.server.type, "node");
  assert.equal(manifest.server.entry_point, "server/index.js");
  assert.equal(manifest.server.mcp_config.command, "node");
  assert.deepEqual(manifest.server.mcp_config.args, ["${__dirname}/server/index.js"]);
});

test("manifest keeps the setup surface bounded and local", () => {
  assert.equal(manifest.manifest_version, "0.3");
  assert.equal(manifest.user_config.launcher_command.type, "string");
  assert.equal(manifest.user_config.launcher_args_json.type, "string");
  assert.match(manifest.user_config.launcher_args_json.description, /stdio/);
  assert.deepEqual(manifest.compatibility.platforms, ["darwin", "win32"]);
  assert.deepEqual(manifest.privacy_policies, [
    "https://orenlab.github.io/codeclone/privacy-policy/",
  ]);
  assert.equal(manifest.documentation, "https://orenlab.github.io/codeclone/claude-desktop-bundle/");
  assert.equal(manifest.tools_generated, true);
  assert.equal(manifest.tools.length, 5);
});
