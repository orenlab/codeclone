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
        };
    }
    return originalLoad.call(this, request, parent, isMain);
};

const {
    formatBaselineState,
    formatBaselineTags,
} = require("../src/formatters");
const {
    renderSecuritySurfaceMarkdown,
    renderTriageMarkdown,
} = require("../src/renderers");

moduleInternals._load = originalLoad;

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

test("renderSecuritySurfaceMarkdown keeps report-only security posture explicit", () => {
    const markdown = renderSecuritySurfaceMarkdown({
        path: "pkg/client.py",
        start_line: 42,
        end_line: 47,
        module: "pkg.client",
        qualname: "pkg.client:send",
        category: "network_boundary",
        capability: "requests_call",
        evidence_symbol: "requests.post",
        source_kind: "production",
        location_scope: "callable",
        classification_mode: "exact_call",
        coverage_overlap: true,
        scope_gap_hotspot: true,
    });

    assert.match(markdown, /# Security Surface/);
    assert.match(markdown, /Location: `pkg\/client.py:42-47`/);
    assert.match(markdown, /Category: Network boundary/);
    assert.match(markdown, /Review signal: Callable · scope gap/);
    assert.match(markdown, /not as a vulnerability claim/);
    assert.match(markdown, /Coverage Join marks this callable as a scope gap/);
});
