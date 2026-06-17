"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
    buildBulkConfirmDetail,
    dedupeGovernanceNodes,
    distinctRecordTypes,
    formatBulkResultSummary,
    recordIdFromGovernanceNode,
    recordIdFromTreeItemId,
    resolveGovernanceTargets,
} = require("../src/memoryBulkSelection");

test("recordIdFromTreeItemId extracts draft and stale ids", () => {
    assert.equal(recordIdFromTreeItemId("memory-draft-mem-abc"), "mem-abc");
    assert.equal(recordIdFromTreeItemId("memory-stale-mem-abc"), "mem-abc");
    assert.equal(recordIdFromTreeItemId("memory-status"), "");
});

test("recordIdFromGovernanceNode accepts draft and stale nodes", () => {
    assert.equal(
        recordIdFromGovernanceNode({
            nodeType: "memoryStale",
            record: {id: "mem-stale"},
        }),
        "mem-stale"
    );
});

test("dedupeGovernanceNodes keeps first occurrence per record id", () => {
    const nodes = [
        {nodeType: "memoryDraft", record: {id: "mem-1"}},
        {nodeType: "memoryStale", record: {id: "mem-1"}},
        {nodeType: "memoryDraft", record: {id: "mem-2"}},
    ];
    assert.equal(dedupeGovernanceNodes(nodes).length, 2);
});

test("resolveGovernanceTargets prefers multi-select tree items", () => {
    const targets = resolveGovernanceTargets(
        {nodeType: "memoryDraft", record: {id: "mem-primary"}},
        [
            {id: "memory-draft-mem-a"},
            {id: "memory-stale-mem-b"},
        ]
    );
    assert.deepEqual(
        targets.map((node) => [node.nodeType, node.record.id]),
        [
            ["memoryDraft", "mem-a"],
            ["memoryStale", "mem-b"],
        ]
    );
});

test("resolveGovernanceTargets keeps stale primary node", () => {
    const targets = resolveGovernanceTargets(
        {
            nodeType: "memoryStale",
            record: {id: "mem-stale", status: "stale"},
        },
        undefined
    );
    assert.equal(targets.length, 1);
    assert.equal(targets[0].nodeType, "memoryStale");
});

test("buildBulkConfirmDetail previews statements and overflow", () => {
    const detail = buildBulkConfirmDetail(
        [
            {
                nodeType: "memoryDraft",
                record: {
                    id: "mem-1",
                    type: "change_rationale",
                    statement: "Anchor drift policy",
                },
            },
            {
                nodeType: "memoryStale",
                record: {
                    id: "mem-2",
                    type: "module_role",
                    statement: "Second stale",
                },
            },
            {
                nodeType: "memoryDraft",
                record: {
                    id: "mem-3",
                    type: "module_role",
                    statement: "Third draft",
                },
            },
            {
                nodeType: "memoryDraft",
                record: {
                    id: "mem-4",
                    type: "module_role",
                    statement: "Fourth draft",
                },
            },
        ],
        "approve",
        2
    );
    assert.match(detail, /change_rationale/);
    assert.match(detail, /…and 2 more/);
    assert.match(detail, /Approved records become active engineering memory/);
});

test("formatBulkResultSummary reports success and failure counts", () => {
    const summary = formatBulkResultSummary(
        {
            succeeded: ["mem-1", "mem-2"],
            failed: [{recordId: "mem-3", message: "already active"}],
        },
        "approve"
    );
    assert.match(summary, /2 memory record\(s\) approved/);
    assert.match(summary, /1 failed: mem-3/);
});

test("distinctRecordTypes returns sorted unique types", () => {
    assert.deepEqual(
        distinctRecordTypes([
            {type: "module_role"},
            {type: "change_rationale"},
            {type: "module_role"},
            {type: ""},
        ]),
        ["change_rationale", "module_role"]
    );
});
