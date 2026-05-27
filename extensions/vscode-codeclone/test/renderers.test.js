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
    renderBlastRadiusMarkdown,
    renderBlastRadiusSvgHtml,
    renderCoverageJoinMarkdown,
    renderSecuritySurfaceMarkdown,
    renderOverloadedModuleMarkdown,
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

test("renderOverloadedModuleMarkdown does not call non-candidates candidates", () => {
    const markdown = renderOverloadedModuleMarkdown({
        path: "pkg/large.py",
        module: "pkg.large",
        candidate_status: "non_candidate",
        source_kind: "production",
        score: 0.83,
        loc: 500,
        callable_count: 12,
        complexity_total: 42,
        complexity_max: 9,
        fan_in: 4,
        fan_out: 7,
        total_deps: 11,
        import_edges: 8,
        reimport_edges: 1,
        reimport_ratio: 0.125,
        instability: 0.63,
        hub_balance: 0.72,
        candidate_reasons: [],
    });

    assert.match(markdown, /# Overloaded Module/);
    assert.match(markdown, /Status: non-candidate/);
    assert.doesNotMatch(markdown, /# Overloaded Module Candidate/);
    assert.match(markdown, /not an overloaded-module candidate/);
});

test("renderCoverageJoinMarkdown explains joined coverage review context", () => {
    const markdown = renderCoverageJoinMarkdown({
        path: "pkg/service.py",
        start_line: 12,
        end_line: 18,
        qualname: "pkg.service:run",
        cyclomatic_complexity: 11,
        risk: "medium",
        coverage_permille: 420,
        coverage_hotspot: true,
    });

    assert.match(markdown, /# Coverage Join Review Item/);
    assert.match(markdown, /Location: `pkg\/service.py:12-18`/);
    assert.match(markdown, /Review signal: low coverage/);
    assert.match(markdown, /Coverage: 42%/);
    assert.match(markdown, /joined coverage review context/);
});

test("renderBlastRadiusMarkdown produces a structured blast radius brief", () => {
    const markdown = renderBlastRadiusMarkdown(
        {
            run_id: "abc123",
            origin: ["src/core.py", "src/utils.py"],
            depth: "transitive",
            radius_level: "medium",
            direct_dependents: ["src/cli.py", "src/api.py"],
            transitive_dependents: ["tests/test_cli.py"],
            clone_cohort_members: ["src/compat.py"],
            in_dependency_cycle: [],
            structural_risk: {
                high_complexity_in_blast_zone: ["src/cli.py"],
                high_coupling_in_blast_zone: [],
                low_coverage_in_blast_zone: [],
                overloaded_modules_in_blast_zone: [],
            },
            do_not_touch: [
                {
                    path: "codeclone.baseline.json",
                    reason: "baseline state requires separate changes",
                    category: "baseline_or_generated_state",
                    severity: "hard",
                },
            ],
            review_context: [],
            guardrails: [
                "review direct dependents before editing public behavior",
            ],
        },
        "demo-repo"
    );

    assert.match(markdown, /# Blast Radius/);
    assert.match(markdown, /Run: `abc123`/);
    assert.match(markdown, /Workspace: `demo-repo`/);
    assert.match(markdown, /Radius level: \*\*Medium\*\*/);
    assert.match(markdown, /Origin: 2 files/);
    assert.match(markdown, /Direct dependents: 2/);
    assert.match(markdown, /Transitive dependents: 1/);
    assert.match(markdown, /Clone cohort: 1/);
    assert.match(markdown, /`src\/core.py`/);
    assert.match(markdown, /`src\/cli.py`/);
    assert.match(markdown, /`src\/compat.py`/);
    assert.match(markdown, /High complexity in blast zone/);
    assert.match(markdown, /codeclone\.baseline\.json/);
    assert.match(markdown, /review direct dependents/);
});

test("renderBlastRadiusSvgHtml produces valid HTML with SVG and CSP", () => {
    const html = renderBlastRadiusSvgHtml(
        {
            run_id: "def456",
            origin: ["src/engine.py"],
            depth: "direct",
            radius_level: "low",
            direct_dependents: ["src/runner.py"],
            transitive_dependents: [],
            clone_cohort_members: [],
            in_dependency_cycle: [],
            structural_risk: {},
            do_not_touch: [],
            review_context: [],
            guardrails: [],
        },
        "test-workspace",
        "abc123nonce"
    );

    assert.match(html, /<!DOCTYPE html>/);
    assert.match(html, /nonce-abc123nonce/);
    assert.match(html, /Blast Radius/);
    assert.match(html, /badge-low/);
    assert.match(html, /<svg/);
    assert.match(html, /Origin/);
    assert.match(html, /1 file\b/);
    assert.match(html, /Direct \(1\)/);
    assert.match(html, /src\/engine\.py/);
    assert.match(html, /src\/runner\.py/);
    assert.doesNotMatch(html, /Transitive/);
    assert.doesNotMatch(html, /Clone cohort/);
});

test("renderBlastRadiusSvgHtml escapes HTML in file paths", () => {
    const html = renderBlastRadiusSvgHtml(
        {
            run_id: "esc1",
            origin: ['src/<script>alert("xss")</script>.py'],
            depth: "direct",
            radius_level: "high",
            direct_dependents: [],
            transitive_dependents: [],
            clone_cohort_members: [],
            in_dependency_cycle: [],
            structural_risk: {},
            do_not_touch: [],
            review_context: [],
            guardrails: [],
        },
        "xss-test",
        "safenonce"
    );

    assert.doesNotMatch(html, /<script>alert/);
    assert.match(html, /&lt;script&gt;/);
});
