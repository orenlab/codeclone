"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");

const originalLoad = Module._load;
Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "vscode") {
        return {
            ThemeIcon: class ThemeIcon {},
            ThemeColor: class ThemeColor {},
        };
    }
    return originalLoad.call(this, request, parent, isMain);
};

const {
    formatBaselineState,
    formatBaselineTags,
} = require("../src/formatters");
const {renderTriageMarkdown} = require("../src/renderers");

Module._load = originalLoad;

test("formatBaselineState explains comparison without a valid baseline", () => {
    assert.equal(
        formatBaselineState({
            status: "mismatch_python_version",
            trusted: false,
            compared_without_valid_baseline: true,
        }),
        "mismatch_python_version · untrusted · comparing without valid baseline"
    );
    assert.equal(
        formatBaselineTags({
            baseline_python_tag: "cp313",
            runtime_python_tag: "cp314",
        }),
        "baseline cp313 · runtime cp314"
    );
});

test("renderTriageMarkdown surfaces baseline mismatch context compactly", () => {
    const markdown = renderTriageMarkdown({
        currentRunId: "abcd1234",
        folder: {name: "demo"},
        latestSummary: {
            baseline: {
                status: "mismatch_python_version",
                trusted: false,
                compared_without_valid_baseline: true,
                baseline_python_tag: "cp313",
                runtime_python_tag: "cp314",
            },
            health_scope: "repository",
            health: {score: 87, grade: "B"},
            findings: {
                total: 4,
                production: 1,
                new_by_source_kind: {tests: 1},
            },
        },
        latestTriage: {
            focus: "production",
            findings: {
                outside_focus: 3,
                by_source_kind: {production: 1, tests: 3},
            },
            top_hotspots: {items: []},
            top_suggestions: {items: []},
        },
    });

    assert.match(
        markdown,
        /Baseline: mismatch_python_version · untrusted · comparing without valid baseline/
    );
    assert.match(markdown, /Baseline tags: baseline cp313 · runtime cp314/);
});
