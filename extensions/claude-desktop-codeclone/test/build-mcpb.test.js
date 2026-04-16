"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const rootDir = path.resolve(__dirname, "..");
const manifest = JSON.parse(
    fs.readFileSync(path.join(rootDir, "manifest.json"), "utf8"),
);

test("build script validates the current manifest shape", async () => {
    const {validateManifest} = await import("../scripts/build-mcpb.mjs");

    assert.equal(validateManifest(manifest), manifest);
});

test("build script rejects malformed manifest payloads before zipping", async () => {
    const {validateManifest} = await import("../scripts/build-mcpb.mjs");

    assert.throws(
        () =>
            validateManifest({
                manifest_version: "0.3",
                name: "codeclone",
                version: "2.0.0",
                server: {type: "node", mcp_config: {command: "node", args: []}},
                tools: [],
            }),
        /server\.entry_point/
    );
});
