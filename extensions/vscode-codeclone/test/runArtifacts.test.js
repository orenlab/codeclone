"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
    fetchProductionTriage,
    loadRunArtifacts,
    shouldUseCachedTriage,
} = require("../src/runArtifacts");

test("shouldUseCachedTriage respects cooldown, run id, and stale flag", () => {
    const base = {
        now: 10_000,
        currentRunId: "run-a",
        lastTriageFetchAt: 8_000,
        lastTriageFetchRunId: "run-a",
        stale: false,
        cooldownMs: 5_000,
    };
    assert.equal(shouldUseCachedTriage(base, true), true);
    assert.equal(shouldUseCachedTriage({...base, now: 14_000}, true), false);
    assert.equal(shouldUseCachedTriage({...base, stale: true}, true), false);
    assert.equal(
        shouldUseCachedTriage({...base, lastTriageFetchRunId: "run-b"}, true),
        false
    );
    assert.equal(shouldUseCachedTriage(base, false), false);
});

test("fetchProductionTriage uses bounded hotspot and suggestion limits", async () => {
    const calls = [];
    const client = {
        callTool(method, payload) {
            calls.push([method, payload]);
            return Promise.resolve({focus: "production"});
        },
    };
    const triage = await fetchProductionTriage(client, "run-42");
    assert.deepEqual(calls, [
        [
            "get_production_triage",
            {run_id: "run-42", max_hotspots: 5, max_suggestions: 5},
        ],
    ]);
    assert.deepEqual(triage, {focus: "production"});
});

test("loadRunArtifacts starts MCP reads and git snapshot together", async () => {
    const started = [];
    /** @type {Map<string, (value: any) => void>} */
    const resolvers = new Map();
    const client = {
        callTool(method, payload) {
            started.push([method, payload]);
            return new Promise((resolve) => {
                resolvers.set(method, resolve);
            });
        },
    };
    let gitSnapshotStarted = false;
    /** @type {(value: any) => void} */
    let resolveGitSnapshot = () => {};

    const promise = loadRunArtifacts(
        client,
        {uri: {fsPath: "/workspace/repo"}},
        "run-123",
        () =>
            new Promise((resolve) => {
                gitSnapshotStarted = true;
                resolveGitSnapshot = resolve;
            })
    );

    assert.deepEqual(
        started.map(([method]) => method),
        [
            "get_run_summary",
            "get_production_triage",
            "get_report_section",
            "list_reviewed_findings",
        ]
    );
    assert.equal(gitSnapshotStarted, true);

    const resolveSummary = resolvers.get("get_run_summary");
    const resolveTriage = resolvers.get("get_production_triage");
    const resolveMetrics = resolvers.get("get_report_section");
    const resolveReviewed = resolvers.get("list_reviewed_findings");
    assert.ok(resolveSummary);
    assert.ok(resolveTriage);
    assert.ok(resolveMetrics);
    assert.ok(resolveReviewed);
    resolveSummary({
        version: "2.0.0",
        coverage_join: {status: "ok", scope_gap_hotspots: 1},
    });
    resolveTriage({hotspots: []});
    resolveMetrics({summary: {health: {score: 90}}});
    resolveReviewed({items: [{id: "f1"}]});
    resolveGitSnapshot({head: "abc123"});

    assert.deepEqual(await promise, {
        summary: {
            version: "2.0.0",
            coverage_join: {status: "ok", scope_gap_hotspots: 1},
        },
        triage: {hotspots: []},
        metricsSummary: {
            health: {score: 90},
            coverage_join: {status: "ok", scope_gap_hotspots: 1},
        },
        reviewedItems: [{id: "f1"}],
        gitSnapshot: {head: "abc123"},
    });
});
