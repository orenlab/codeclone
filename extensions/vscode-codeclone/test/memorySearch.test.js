"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");

const moduleInternals = /** @type {{_load: Function}} */ (
    /** @type {unknown} */ (Module)
);
const originalLoad = moduleInternals._load;
moduleInternals._load = function patchedLoad(request, parent, isMain) {
    if (request === "vscode") {
        return {
            ThemeIcon: class ThemeIcon {},
            ThemeColor: class ThemeColor {},
            window: {},
            workspace: {getConfiguration: () => ({get: () => undefined})},
            ConfigurationTarget: {WorkspaceFolder: 3},
        };
    }
    return originalLoad.call(this, request, parent, isMain);
};

const {
    sanitizeSearchQuery,
    isValidMemoryRecordId,
    normalizeMemorySearchPath,
    buildSearchToolArgs,
    recordToQuickPickItem,
} = require("../src/memorySearch");
const {
    renderMemorySearchHtml,
    escapeHtml,
} = require("../src/memorySearchRenderer");
const {memoryRecordCommandUri} = require("../src/memorySearch");

moduleInternals._load = originalLoad;

test("sanitizeSearchQuery rejects short, long, and control-character queries", () => {
    assert.equal(sanitizeSearchQuery("a"), "Enter at least 2 characters.");
    assert.equal(sanitizeSearchQuery("ok"), null);
    const tooLong = sanitizeSearchQuery("x".repeat(201));
    assert.ok(tooLong);
    assert.match(tooLong, /at most 200/);
    const control = sanitizeSearchQuery("bad\u0001query");
    assert.ok(control);
    assert.match(control, /control characters/);
});

test("isValidMemoryRecordId accepts mem- uuid ids only", () => {
    assert.equal(isValidMemoryRecordId("mem-30febd83c0b14c0f9f0e2a1b3c4d5e6f"), true);
    assert.equal(isValidMemoryRecordId("mem-proposal-abc"), false);
    assert.equal(isValidMemoryRecordId("../mem-30febd83c0b14c0f9f0e2a1b3c4d5e6f"), false);
});

test("normalizeMemorySearchPath rejects root and traversal paths", () => {
    assert.equal(normalizeMemorySearchPath("src/a.py"), "src/a.py");
    assert.equal(normalizeMemorySearchPath("."), null);
    assert.equal(normalizeMemorySearchPath("../secret"), null);
    assert.equal(normalizeMemorySearchPath("/abs.py"), null);
});

test("buildSearchToolArgs maps UI options to MCP tool fields", () => {
    const args = buildSearchToolArgs("/repo", "blast radius", {
        semantic: true,
        includeDrafts: true,
        includeStale: false,
        maxResults: 15,
        detailLevel: "full",
    });
    assert.deepEqual(args, {
        root: "/repo",
        mode: "search",
        query: "blast radius",
        semantic: true,
        include_drafts: true,
        include_stale: false,
        max_results: 15,
        detail_level: "full",
    });
});

test("recordToQuickPickItem surfaces type, status, and preview", () => {
    const item = recordToQuickPickItem(
        {
            id: "mem-30febd83c0b14c0f9f0e2a1b3c4d5e6f",
            type: "risk_note",
            status: "active",
            statement: "Keep MCP scope explicit.",
            subjects: [{subject_key: "codeclone/memory/paths.py", subject_kind: "file"}],
        },
        0
    );
    assert.match(item.label, /risk_note/);
    assert.match(item.description, /^mem-/);
    assert.match(item.detail, /MCP scope/);
});

test("renderMemorySearchHtml escapes query and uses allowlisted command links", () => {
    const html = renderMemorySearchHtml({
        query: '<script>alert(1)</script>',
        workspaceName: "demo",
        nonce: "abc123",
        result: {
            response: {
                mode: "search",
                detail_level: "compact",
                semantic: {used: false, reason: "disabled"},
                payload: {
                    records: [
                        {
                            id: "mem-30febd83c0b14c0f9f0e2a1b3c4d5e6f",
                            type: "change_rationale",
                            status: "draft",
                            confidence: "medium",
                            statement: "Test <unsafe>",
                        },
                    ],
                    record_count: 1,
                    truncated: false,
                    retrieval_policy: {drafts_included: false},
                },
            },
        },
    });
    assert.doesNotMatch(html, /<script>/);
    assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
    assert.match(html, /command:codeclone\.openMemoryRecordById\?/);
    assert.match(html, /Test &lt;unsafe&gt;/);
});

test("memoryRecordCommandUri encodes record id as JSON array argument", () => {
    const uri = memoryRecordCommandUri("mem-30febd83c0b14c0f9f0e2a1b3c4d5e6f");
    assert.match(uri, /^command:codeclone\.openMemoryRecordById\?/);
    const encoded = uri.split("?")[1];
    assert.deepEqual(JSON.parse(decodeURIComponent(encoded)), [
        "mem-30febd83c0b14c0f9f0e2a1b3c4d5e6f",
    ]);
});

test("escapeHtml neutralizes HTML metacharacters", () => {
    assert.equal(escapeHtml(`a&b<"c>`), "a&amp;b&lt;&quot;c&gt;");
});
