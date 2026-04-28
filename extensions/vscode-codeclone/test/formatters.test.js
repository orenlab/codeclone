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
    formatCoverageJoinMeasuredUnits,
    formatCoverageJoinPercent,
    formatCoverageJoinStatus,
    formatCoverageJoinSummary,
    formatSecuritySurfaceLocation,
    formatSecuritySurfaceReviewSignal,
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
