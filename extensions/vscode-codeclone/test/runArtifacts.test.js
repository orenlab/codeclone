"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {loadRunArtifacts} = require("../src/runArtifacts");

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
    resolveSummary({version: "2.0.0"});
    resolveTriage({hotspots: []});
    resolveMetrics({summary: {health: {score: 90}}});
    resolveReviewed({items: [{id: "f1"}]});
    resolveGitSnapshot({head: "abc123"});

    assert.deepEqual(await promise, {
        summary: {version: "2.0.0"},
        triage: {hotspots: []},
        metricsSummary: {health: {score: 90}},
        reviewedItems: [{id: "f1"}],
        gitSnapshot: {head: "abc123"},
    });
});
