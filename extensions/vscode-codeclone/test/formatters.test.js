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
    coverageJoinPayload,
    formatCoverageJoinMeasuredUnits,
    formatCoverageJoinPercent,
    formatCoverageJoinStatus,
    formatCoverageJoinSummary,
} = require("../src/formatters");

Module._load = originalLoad;

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
