"use strict";

// Sync pins for the three hand-maintained hotspot mode structures in
// src/constants.js (HOTSPOT_GROUPS, HOTSPOT_FOCUS_MODES, HOTSPOT_GROUPS_BY_MODE)
// plus a documenting pin for the silent fallback in activeHotspotGroupIds.
//
// Every set expectation below is DERIVED from the structures under test —
// never a third hand-written dictionary that would itself need syncing.

const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");

class StubThemeIcon {
    constructor(id) {
        this.id = id;
    }
}

const moduleInternals = /** @type {{_load: Function}} */ (
    /** @type {unknown} */ (Module)
);
const originalLoad = moduleInternals._load;
moduleInternals._load = function patchedLoad(request, parent, isMain) {
    if (request === "vscode") {
        return {
            ThemeIcon: StubThemeIcon,
            ThemeColor: class ThemeColor {},
            window: {activeTextEditor: undefined},
            workspace: {
                workspaceFolders: undefined,
                getWorkspaceFolder: () => undefined,
                getConfiguration: () => ({get: (_key, fallback) => fallback}),
            },
        };
    }
    return originalLoad.call(this, request, parent, isMain);
};

const {
    HOTSPOT_GROUPS,
    HOTSPOT_FOCUS_MODES,
    HOTSPOT_GROUPS_BY_MODE,
} = require("../src/constants");
const {CodeCloneController} = require("../src/extension");

test("P1: every declared focus mode owns a row in HOTSPOT_GROUPS_BY_MODE", () => {
    const modeIds = HOTSPOT_FOCUS_MODES.map((mode) => mode.id);
    const rowKeys = Object.keys(HOTSPOT_GROUPS_BY_MODE);
    const modesWithoutRow = modeIds.filter((id) => !rowKeys.includes(id));
    assert.deepEqual(
        modesWithoutRow,
        [],
        "focus modes declared in HOTSPOT_FOCUS_MODES without a HOTSPOT_GROUPS_BY_MODE " +
            "row silently fall back to the recommended selection in " +
            "activeHotspotGroupIds — the user picks one mode and gets another"
    );
});

test("P1: every HOTSPOT_GROUPS_BY_MODE key is a declared focus mode", () => {
    const modeIds = new Set(HOTSPOT_FOCUS_MODES.map((mode) => mode.id));
    const orphanRows = Object.keys(HOTSPOT_GROUPS_BY_MODE).filter(
        (key) => !modeIds.has(key)
    );
    assert.deepEqual(
        orphanRows,
        [],
        "HOTSPOT_GROUPS_BY_MODE rows without a matching HOTSPOT_FOCUS_MODES entry " +
            "are dead table rows no user can ever select"
    );
});

test("P2: every group id referenced by HOTSPOT_GROUPS_BY_MODE exists in HOTSPOT_GROUPS", () => {
    const groupIds = new Set(HOTSPOT_GROUPS.map((group) => group.id));
    for (const [modeId, ids] of Object.entries(HOTSPOT_GROUPS_BY_MODE)) {
        const unknownIds = ids.filter((id) => !groupIds.has(id));
        assert.deepEqual(
            unknownIds,
            [],
            `mode "${modeId}" references group ids missing from HOTSPOT_GROUPS — ` +
                "a typo here silently produces an empty or incomplete selection"
        );
    }
});

test("P3: mode 'all' promises every hotspot group", () => {
    assert.deepEqual(
        HOTSPOT_GROUPS_BY_MODE.all,
        HOTSPOT_GROUPS.map((group) => group.id),
        "the 'all' description promises every hotspot group, including empty ones"
    );
});

test("P3: mode 'recommended' lists every hotspot group — the difference from 'all' lives in shouldShowGroup", () => {
    // FACT, pinned deliberately: recommended and all carry the SAME group list.
    // The user-visible difference between the two modes is NOT in this table —
    // it lives in shouldShowGroup(), where recommended (non-specific) hides
    // count-zero groups while 'all' returns the list unfiltered.
    // Do not "fix" this equality silently: shrinking the recommended list here
    // would silently drop review surfaces from the default mode.
    assert.deepEqual(
        HOTSPOT_GROUPS_BY_MODE.recommended,
        HOTSPOT_GROUPS.map((group) => group.id),
        "recommended must list every hotspot group; visibility filtering is " +
            "shouldShowGroup's job, not this table's"
    );
});

test("P3: single-focus modes map to exactly their own group", () => {
    // Contract stated by each mode's description in HOTSPOT_FOCUS_MODES:
    // 'new' focuses baseline-new findings, 'production' focuses production
    // hotspots, 'changed' focuses diff-touching findings.
    assert.deepEqual(HOTSPOT_GROUPS_BY_MODE.new, ["newRegressions"]);
    assert.deepEqual(HOTSPOT_GROUPS_BY_MODE.production, ["productionHotspots"]);
    assert.deepEqual(HOTSPOT_GROUPS_BY_MODE.changed, ["changedFiles"]);
});

test("P3: mode 'reportOnly' maps to exactly securitySurfaces and overloadedModules", () => {
    assert.deepEqual(HOTSPOT_GROUPS_BY_MODE.reportOnly, [
        "securitySurfaces",
        "overloadedModules",
    ]);
});

/**
 * Minimal state for the fallback probe. changedSummary is truthy so the
 * changedFiles group stays visible under specific-mode semantics; the review
 * artifact arrays keep count lookups safe if evaluation order ever changes.
 */
function fallbackProbeState() {
    return {
        changedSummary: {},
        metricsSummary: {},
        reviewArtifacts: {
            newRegressions: [],
            productionHotspots: [],
            changedFiles: [],
            coverageJoin: [],
            overloadedModules: [],
            securitySurfaces: [],
        },
    };
}

test("P4: unknown focus mode silently falls back to the recommended selection (documenting pin)", () => {
    // DOCUMENTING PIN, not an endorsement. activeHotspotGroupIds resolves an
    // unknown mode via `|| HOTSPOT_GROUPS_BY_MODE.recommended` without any
    // warning. Worse: an unknown mode counts as "specific" for
    // isSpecificFocusMode (it is neither 'recommended' nor 'all'), so the
    // fallback list passes shouldShowGroup WITHOUT the count-based filtering
    // the real 'recommended' mode applies — the user picks a mode that does
    // not exist and sees strictly more than 'recommended' would show on a
    // quiet run. Candidate for a loud failure instead; maintainer's decision.
    const controller = /** @type {any} */ (
        Object.create(CodeCloneController.prototype)
    );
    controller.hotspotFocusMode = "modeThatWasNeverDeclared";
    const ids = controller.activeHotspotGroupIds(fallbackProbeState());
    assert.deepEqual(
        ids,
        HOTSPOT_GROUPS_BY_MODE.recommended,
        "the silent fallback must return the recommended selection as-is; " +
            "if this pin turns red because the fallback became a loud failure, " +
            "replace the pin with one for the new contract"
    );
});
