"use strict";

const {test} = require("node:test");
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
    renderSessionStatsHtml,
    renderAuditTrailHtml,
    renderSessionStatsMarkdown,
    renderAuditTrailMarkdown,
} = require("../src/workspaceInsightsRenderer");

moduleInternals._load = originalLoad;

const SAMPLE_SESSION = {
    status: "ok",
    workspace: {
        root: "/tmp/repo",
        health: "idle",
        intent_registry_backend: "file",
        intent_registry_storage: ".cache/codeclone/intents",
    },
    counts: {
        live_agents: 0,
        active_intents: 0,
        visible_intents: 0,
        stale: 0,
        expired: 0,
        recoverable: 0,
    },
    latest_run: {
        run_id: null,
        cache_present: false,
    },
    audit: {enabled: false},
    token_footprint: {
        total_tokens: null,
        tool_calls: 0,
    },
    top_workflows: [],
    agents: [],
};

const SAMPLE_AUDIT_DISABLED = {
    status: "disabled",
    message: "audit off",
    counts: {
        total_events: 0,
        intent_events: 0,
        contract_events: 0,
        receipt_events: 0,
        violation_events: 0,
    },
    events: [],
};

test("renderSessionStatsHtml includes CSP nonce and escapes workspace name", () => {
    const html = renderSessionStatsHtml(
        SAMPLE_SESSION,
        '<script>alert(1)</script>',
        "nonce-abc"
    );
    assert.match(html, /style-src 'nonce-nonce-abc'/);
    assert.match(html, /Workspace Session Stats/);
    assert.doesNotMatch(html, /<script>alert/);
    assert.match(html, /&lt;script&gt;alert/);
});

test("renderAuditTrailHtml shows disabled banner", () => {
    const html = renderAuditTrailHtml(SAMPLE_AUDIT_DISABLED, "demo", "nonce-1");
    assert.match(html, /disabled/);
    assert.match(html, /audit off/);
    assert.match(html, /Content-Security-Policy/);
});

test("renderSessionStatsMarkdown summarizes health", () => {
    const md = renderSessionStatsMarkdown(SAMPLE_SESSION);
    assert.match(md, /Workspace health: \*\*idle\*\*/);
    assert.match(md, /Latest run: none/);
});

test("renderAuditTrailMarkdown includes status line", () => {
    const md = renderAuditTrailMarkdown(SAMPLE_AUDIT_DISABLED);
    assert.match(md, /Status: \*\*disabled\*\*/);
});

test("renderAuditTrailHtml reads payload_footprint calls/tokens keys from audit reader", () => {
    const html = renderAuditTrailHtml(
        {
            status: "ok",
            database: {path: ".cache/codeclone/audit.sqlite3"},
            counts: {
                total_events: 10,
                intent_events: 4,
                contract_events: 3,
                receipt_events: 2,
                violation_events: 1,
            },
            token_summary: {
                total_estimated_tokens: 48000,
                token_encoding: "chars/4",
                token_event_count: 12,
            },
            payload_footprint: {
                encoding: "chars/4",
                tool_calls: 12,
                total_tokens: 48000,
                avg_tokens: 4000,
                p95_tokens: 9000,
                max_tokens: 12000,
                top_workflows: [
                    {
                        workflow_kind: "intent",
                        workflow_id: "intent-abc",
                        calls: 5,
                        tokens: 12000,
                    },
                ],
            },
            events: [],
        },
        "demo",
        "nonce-footprint"
    );
    assert.match(html, /Payload footprint \(retention window\)/);
    assert.match(html, /48,000 total tokens/);
    assert.match(html, /intent:intent-abc/);
    assert.match(html, />~12000</);
    assert.match(html, />5</);
    assert.doesNotMatch(html, />~0<\/td><td class="num">0<\/td>/);
});
