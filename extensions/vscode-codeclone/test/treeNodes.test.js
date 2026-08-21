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
    buildRunOverviewDetailNodes,
    buildServerSessionDetailNodes,
} = require("../src/treeNodes");

function plainDetailNode(label, description, command) {
    return {nodeType: "detail", label, description, command};
}

function runInput(overrides = {}) {
    return {
        state: {
            folder: {name: "fixture-workspace"},
            currentRunId: "run-1234",
            stale: false,
            staleReason: null,
            latestSummary: {
                inventory: {files: 12, lines: 3400, functions: 88, classes: 7},
                baseline: {
                    status: "ok",
                    trusted: true,
                    interpreter_provenance: "foreign",
                    baseline_python_tag: "cp312",
                    runtime_python_tag: "cp314",
                },
                metrics_baseline: {status: "ok", trusted: true},
                cache: {used: true, freshness: "fresh"},
            },
        },
        currentAnalysisSettings: {
            label: "Defaults",
            thresholdSummary: "min 10/6",
        },
        pendingAnalysisSettings: null,
        launchSpec: {
            command: "uv",
            args: ["run", "codeclone-mcp"],
            source: "workspaceLocal",
        },
        baselineDriftSummary: "0 new · +0 clones · +2 health",
        ...overrides,
    };
}

test("run overview details pin the provenance rows when the baseline is foreign and a runtime launched", () => {
    const nodes = buildRunOverviewDetailNodes(runInput(), plainDetailNode);
    assert.deepEqual(
        nodes.map((node) => node.label),
        [
            "Workspace",
            "Run ID",
            "Analysis depth",
            "Threshold profile",
            "Freshness",
            "Files",
            "Parsed lines",
            "Callables",
            "Classes",
            "Baseline",
            "Baseline tags",
            "Runtime source",
            "Metrics baseline",
            "Baseline drift",
            "Cache",
        ]
    );
    const byLabel = new Map(nodes.map((node) => [node.label, node]));
    assert.equal(
        byLabel.get("Baseline tags").description,
        "baseline cp312 · runtime cp314"
    );
    assert.equal(
        byLabel.get("Runtime source").description,
        "workspace-local launcher (uv run codeclone-mcp)"
    );
});

test("run overview details omit both provenance rows on a same-interpreter run without a launched runtime", () => {
    const input = runInput({launchSpec: null});
    input.state.latestSummary.baseline = {
        status: "ok",
        trusted: true,
        interpreter_provenance: "same",
        baseline_python_tag: "cp314",
        runtime_python_tag: "cp314",
    };
    const nodes = buildRunOverviewDetailNodes(input, plainDetailNode);
    const labels = nodes.map((node) => node.label);
    assert.ok(
        !labels.includes("Baseline tags"),
        "a same-interpreter baseline must not print a Baseline tags row"
    );
    assert.ok(
        !labels.includes("Runtime source"),
        "no launched runtime means no Runtime source row"
    );
    assert.deepEqual(labels, [
        "Workspace",
        "Run ID",
        "Analysis depth",
        "Threshold profile",
        "Freshness",
        "Files",
        "Parsed lines",
        "Callables",
        "Classes",
        "Baseline",
        "Metrics baseline",
        "Baseline drift",
        "Cache",
    ]);
});

test("server session details report the launched runtime source and launcher", () => {
    const nodes = buildServerSessionDetailNodes(
        {
            connected: true,
            serverInfo: {version: "2.1.0"},
            toolCount: 42,
            launchSpec: {
                command: "uv",
                args: ["run", "codeclone-mcp"],
                source: "workspaceLocal",
            },
        },
        plainDetailNode
    );
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
});

test("server session details say 'not started' when no runtime was launched", () => {
    const nodes = buildServerSessionDetailNodes(
        {
            connected: false,
            serverInfo: null,
            toolCount: 0,
            launchSpec: null,
        },
        plainDetailNode
    );
    assert.deepEqual(
        nodes.map((node) => [node.label, node.description]),
        [
            ["Connected", "no"],
            ["CodeClone version", "unknown"],
            ["Available tools", "0"],
            ["Runtime source", "not started"],
            ["Launcher", "not started"],
        ]
    );
});
