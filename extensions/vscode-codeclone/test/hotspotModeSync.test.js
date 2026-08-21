"use strict";

// Sync pins for the three hand-maintained hotspot mode structures in
// src/constants.js (HOTSPOT_GROUPS, HOTSPOT_FOCUS_MODES, HOTSPOT_GROUPS_BY_MODE)
// plus input-contract pins for the hotspot focus mode: the loader normalizes
// stored state to a declared mode, and an undeclared mode fails loudly in the
// mode-table lookups instead of silently borrowing another mode's selection.
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
 * Minimal state for the input-contract pins. changedSummary is truthy so the
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

/**
 * Controller wired with only the workspaceState input boundary, so the loader
 * pins exercise loadHotspotFocusMode against an exact stored value.
 */
function controllerWithStoredMode(storedValue) {
    const controller = /** @type {any} */ (
        Object.create(CodeCloneController.prototype)
    );
    controller.context = {
        workspaceState: {
            get: (_key, fallback) =>
                storedValue === undefined ? fallback : storedValue,
        },
    };
    return controller;
}

test("P4: loader normalizes an undeclared stored focus mode to 'recommended'", () => {
    // workspaceState is an input boundary: whatever survives there from an
    // older install or a foreign writer must be normalized to a declared mode
    // before it becomes controller state — never handed to the mode tables
    // as-is.
    const controller = controllerWithStoredMode("modeThatWasNeverDeclared");
    assert.equal(
        controller.loadHotspotFocusMode(),
        "recommended",
        "an undeclared stored focus mode must be normalized to 'recommended'"
    );
});

test("P4: loader returns every declared focus mode unchanged", () => {
    for (const mode of HOTSPOT_FOCUS_MODES) {
        const controller = controllerWithStoredMode(mode.id);
        assert.equal(
            controller.loadHotspotFocusMode(),
            mode.id,
            `declared focus mode "${mode.id}" must round-trip through the loader`
        );
    }
});

test("P4: loader defaults to 'recommended' when nothing is stored", () => {
    const controller = controllerWithStoredMode(undefined);
    assert.equal(controller.loadHotspotFocusMode(), "recommended");
});

test("P5: an undeclared focus mode fails loudly in activeHotspotGroupIds instead of borrowing the recommended selection", () => {
    // Input contract: loadHotspotFocusMode normalizes stored state and the
    // picker only produces declared modes, so an undeclared mode here can only
    // come from a future setter that violates the input contract. That is the
    // new setter's defect, and it must surface as a loud failure (TypeError
    // class) — not as the silent recommended selection the removed fallback
    // used to substitute.
    const controller = /** @type {any} */ (
        Object.create(CodeCloneController.prototype)
    );
    controller.hotspotFocusMode = "modeThatWasNeverDeclared";
    assert.throws(
        () => controller.activeHotspotGroupIds(fallbackProbeState()),
        TypeError,
        "an undeclared focus mode must fail loudly, not resolve to another " +
            "mode's group selection"
    );
});

test("P5: an undeclared specific focus mode fails loudly in shouldShowGroup", () => {
    // Same input contract, second lookup site: an undeclared mode counts as
    // "specific" (it is neither 'recommended' nor 'all'), so shouldShowGroup
    // consults HOTSPOT_GROUPS_BY_MODE directly. A contract-violating caller
    // must fail loudly here too, not inherit the recommended allow-list.
    const controller = /** @type {any} */ (
        Object.create(CodeCloneController.prototype)
    );
    controller.hotspotFocusMode = "modeThatWasNeverDeclared";
    assert.throws(
        () => controller.shouldShowGroup("newRegressions", fallbackProbeState()),
        TypeError,
        "an undeclared specific focus mode must fail loudly, not inherit " +
            "the recommended mode's allow-list"
    );
});
