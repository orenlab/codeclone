"use strict";

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

const {CodeCloneController} = require("../src/extension");

function fixtureState({foreignBaseline}) {
    return {
        folder: {
            name: "fixture-workspace",
            uri: {toString: () => "file:///fixture", fsPath: "/fixture"},
        },
        currentRunId: "run-1234",
        latestSummary: {
            version: "2.1.0",
            mode: "full",
            health_scope: "repository",
            inventory: {files: 12, lines: 3400, functions: 88, classes: 7},
            baseline: foreignBaseline
                ? {
                    status: "ok",
                    trusted: true,
                    interpreter_provenance: "foreign",
                    baseline_python_tag: "cp312",
                    runtime_python_tag: "cp314",
                }
                : {
                    status: "ok",
                    trusted: true,
                    interpreter_provenance: "same",
                    baseline_python_tag: "cp314",
                    runtime_python_tag: "cp314",
                },
            metrics_baseline: {status: "ok", trusted: true},
            diff: {new_clones: 0, health_delta: 0},
            findings: {new: 0, new_by_source_kind: {}},
            cache: {used: false, freshness: "fresh"},
        },
        metricsSummary: {},
        latestTriage: null,
        changedSummary: null,
        analysisSettings: null,
        reviewed: [],
        lastScope: "workspace",
        lastUpdatedAt: null,
        stale: false,
        staleReason: null,
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

function fixtureController(state, connectionInfo) {
    const controller = Object.create(CodeCloneController.prototype);
    controller.states = new Map([[state.folder.uri.toString(), state]]);
    controller.connectionInfo = connectionInfo;
    controller.hotspotFocusMode = "recommended";
    return controller;
}

const launchedConnection = {
    connected: true,
    serverInfo: {version: "2.1.0"},
    toolCount: 42,
    launchSpec: {
        command: "uv",
        args: ["run", "codeclone-mcp"],
        source: "workspaceLocal",
    },
};

const idleConnection = {
    connected: false,
    serverInfo: null,
    toolCount: 0,
    launchSpec: null,
};

test("extension wires the run overview builder: provenance rows reach the tree", async () => {
    const controller = fixtureController(
        fixtureState({foreignBaseline: true}),
        launchedConnection
    );
    const nodes = await controller.getOverviewChildren({id: "overview.run"});
    const byLabel = new Map(nodes.map((node) => [node.label, node]));
    const baselineTags = byLabel.get("Baseline tags");
    assert.ok(baselineTags, "overview.run must contain the Baseline tags row");
    assert.equal(baselineTags.description, "baseline cp312 · runtime cp314");
    const runtimeSource = byLabel.get("Runtime source");
    assert.ok(runtimeSource, "overview.run must contain the Runtime source row");
    assert.equal(
        runtimeSource.description,
        "workspace-local launcher (uv run codeclone-mcp)"
    );
    for (const node of nodes) {
        assert.equal(node.nodeType, "detail");
        assert.ok(
            node.icon instanceof StubThemeIcon,
            "wiring must decorate builder rows with the controller's ThemeIcon"
        );
        assert.equal(node.icon.id, "circle-small-filled");
    }
});

test("extension wiring stays quiet without provenance: no Baseline tags, no Runtime source", async () => {
    const controller = fixtureController(
        fixtureState({foreignBaseline: false}),
        idleConnection
    );
    const nodes = await controller.getOverviewChildren({id: "overview.run"});
    const labels = nodes.map((node) => node.label);
    assert.ok(labels.length > 0, "overview.run must still render its details");
    assert.ok(!labels.includes("Baseline tags"));
    assert.ok(!labels.includes("Runtime source"));
});

test("extension wires the server session builder: runtime source reaches the tree", async () => {
    const controller = fixtureController(
        fixtureState({foreignBaseline: false}),
        launchedConnection
    );
    const nodes = await controller.getSessionChildren({id: "session.server"});
    assert.deepEqual(
        nodes.map((node) => [node.label, node.description]),
        [
            ["Connected", "yes"],
            ["CodeClone version", "2.1.0"],
            ["Available tools", "42"],
            ["Runtime source", "workspace-local launcher (uv run codeclone-mcp)"],
            ["Launcher", "uv run codeclone-mcp"],
        ]
    );
    for (const node of nodes) {
        assert.ok(node.icon instanceof StubThemeIcon);
        assert.equal(node.icon.id, "circle-small-filled");
    }
});

test("extension session builder reports 'not started' before any runtime launch", async () => {
    const controller = fixtureController(
        fixtureState({foreignBaseline: false}),
        idleConnection
    );
    const nodes = await controller.getSessionChildren({id: "session.server"});
    const byLabel = new Map(nodes.map((node) => [node.label, node]));
    assert.equal(byLabel.get("Runtime source").description, "not started");
    assert.equal(byLabel.get("Launcher").description, "not started");
});
