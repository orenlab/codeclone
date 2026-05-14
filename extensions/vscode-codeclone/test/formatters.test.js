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
    coverageJoinPayload,
    coverageJoinReviewItemCount,
    formatCoverageJoinMeasuredUnits,
    formatCoverageJoinPercent,
    formatCoverageJoinLocation,
    formatCoverageJoinReviewSignal,
    formatCoverageJoinStatus,
    formatCoverageJoinSummary,
    formatOverloadedModuleStatus,
    formatOverloadedModulesSummary,
    formatSecuritySurfaceLocation,
    formatSecuritySurfaceReviewSignal,
    isCoverageJoinReviewItem,
    isOverloadedModuleCandidate,
    overloadedModuleCandidateCount,
    qualityReviewItemCount,
    reportReviewItemCount,
    securitySurfacesPayload,
} = require("../src/formatters");

moduleInternals._load = originalLoad;

test("coverage join formatters render joined summary from canonical metrics facts", () => {
    const payload = {
        status: "ok",
        overall_permille: 993,
        coverage_hotspots: 0,
        scope_gap_hotspots: 1,
        measured_units: 556,
        units: 1364,
    };

    assert.equal(formatCoverageJoinStatus(payload), "joined");
    assert.equal(formatCoverageJoinPercent(payload), "99.3%");
    assert.equal(formatCoverageJoinMeasuredUnits(payload), "556 / 1,364");
    assert.equal(formatCoverageJoinSummary(payload), "99.3% overall · 0 hotspots · 1 scope gap");
    assert.equal(coverageJoinReviewItemCount(payload, []), 1);
});

test("coverage join formatters keep invalid or unavailable states explicit", () => {
    assert.equal(
        formatCoverageJoinSummary({
            status: "invalid",
            source: "/repo/coverage.xml",
        }),
        "invalid · coverage.xml"
    );
    assert.equal(formatCoverageJoinStatus({status: "missing"}), "unavailable");
    assert.equal(formatCoverageJoinPercent({status: "missing"}), "n/a");
    assert.equal(formatCoverageJoinMeasuredUnits({status: "missing"}), "n/a");
});

test("coverage join payload normalizes missing or null metrics family entries", () => {
    assert.deepEqual(coverageJoinPayload(undefined), {});
    assert.deepEqual(coverageJoinPayload({}), {});
    assert.deepEqual(coverageJoinPayload({coverage_join: null}), {});
    assert.deepEqual(coverageJoinPayload({coverage_join: {status: "ok"}}), {
        status: "ok",
    });
});

test("coverage join item formatters expose review-ready locations and signals", () => {
    const hotspot = {
        path: "pkg/service.py",
        start_line: 12,
        end_line: 16,
        coverage_hotspot: true,
    };
    const scopeGap = {
        path: "pkg/service.py",
        start_line: 44,
        scope_gap_hotspot: true,
    };

    assert.equal(formatCoverageJoinLocation(hotspot), "pkg/service.py:12-16");
    assert.equal(formatCoverageJoinReviewSignal(hotspot), "low coverage");
    assert.equal(formatCoverageJoinReviewSignal(scopeGap), "scope gap");
    assert.equal(isCoverageJoinReviewItem(hotspot), true);
    assert.equal(isCoverageJoinReviewItem({coverage_status: "measured"}), false);
    assert.equal(coverageJoinReviewItemCount({}, [hotspot, scopeGap]), 2);
});

test("security surfaces formatters keep summary payloads and review cues explicit", () => {
    assert.deepEqual(securitySurfacesPayload(undefined), {});
    assert.deepEqual(securitySurfacesPayload({}), {});
    assert.deepEqual(
        securitySurfacesPayload({
            security_surfaces: {
                items: 5,
                production: 3,
                report_only: true,
            },
        }),
        {
            items: 5,
            production: 3,
            report_only: true,
        }
    );

    assert.equal(
        formatSecuritySurfaceLocation({
            path: "pkg/client.py",
            start_line: 12,
            end_line: 18,
        }),
        "pkg/client.py:12-18"
    );
    assert.equal(
        formatSecuritySurfaceReviewSignal({
            location_scope: "callable",
            coverage_hotspot: true,
        }),
        "Callable · low coverage"
    );
    assert.equal(
        formatSecuritySurfaceReviewSignal({
            location_scope: "module",
        }),
        "Module · capability present"
    );
});

test("report badge count matches canonical report tab semantics", () => {
    const latestSummary = {
        findings: {
            by_family: {
                clones: 2,
                structural: 3,
            },
        },
    };
    const metricsSummary = {
        complexity: {high_risk: 4},
        coupling: {high_risk: 5},
        cohesion: {low_cohesion: 6},
        overloaded_modules: {candidates: 11},
        coverage_join: {
            status: "ok",
            coverage_hotspots: 0,
            scope_gap_hotspots: 1,
        },
        security_surfaces: {items: 59},
        dependencies: {cycles: 7},
        dead_code: {high_confidence: 8},
    };
    const triage = {
        suggestions: {total: 9},
    };

    assert.equal(qualityReviewItemCount(metricsSummary, {}), 86);
    assert.equal(reportReviewItemCount(latestSummary, metricsSummary, triage, {}), 115);
});

test("report badge count keeps quality fallback when coverage summary is absent", () => {
    const metricsSummary = {
        overloaded_modules: {},
        security_surfaces: {},
    };
    const artifacts = {
        overloadedModules: [
            {candidate_status: "candidate"},
            {candidate_status: "non_candidate"},
        ],
        coverageJoin: [{scope_gap_hotspot: true}],
        securitySurfaces: [{}, {}, {}],
    };

    assert.equal(qualityReviewItemCount(metricsSummary, artifacts), 5);
    assert.equal(reportReviewItemCount({}, metricsSummary, {}, artifacts), 5);
});

test("overloaded modules formatters count candidates, not visible rows", () => {
    const rows = [
        {candidate_status: "candidate"},
        {candidate_status: "non_candidate"},
        {candidate_status: "ranked_only"},
    ];

    assert.equal(formatOverloadedModuleStatus(rows[0]), "candidate");
    assert.equal(formatOverloadedModuleStatus(rows[1]), "non-candidate");
    assert.equal(formatOverloadedModuleStatus(rows[2]), "ranked-only");
    assert.equal(isOverloadedModuleCandidate(rows[0]), true);
    assert.equal(isOverloadedModuleCandidate(rows[1]), false);
    assert.equal(overloadedModuleCandidateCount({candidates: 11}, rows), 11);
    assert.equal(overloadedModuleCandidateCount({}, rows), 1);
    assert.equal(
        formatOverloadedModulesSummary({candidates: 11, total: 287}, rows),
        "11 candidates · top 3 ranked"
    );
});
