"use strict";

/**
 * Pure builders for tree detail nodes that extension.js renders.
 *
 * This module must not require "vscode": node --test loads it directly, so
 * the node inventory it produces — including the provenance rows "Baseline
 * tags" and "Runtime source" — stays pinnable outside VS Code. The only
 * VS Code-specific part of a node, its icon, comes from the injected
 * `detailNode` factory that extension.js supplies from its controller.
 */

const {
    baselineProvenanceDetails,
    formatBaselineState,
    formatBooleanWord,
    formatCacheSummary,
    number,
    safeObject,
} = require("./formatters");
const {launchSpecOrigin} = require("./support");

/**
 * Detail rows for the Overview tree's "Current Run" section.
 *
 * @param {{
 *   state: any,
 *   currentAnalysisSettings: any,
 *   pendingAnalysisSettings: any,
 *   launchSpec: any,
 *   baselineDriftSummary: string,
 * }} input
 * @param {(label: string, description: string, command?: any) => any} detailNode
 * @returns {any[]}
 */
function buildRunOverviewDetailNodes(input, detailNode) {
    const {
        state,
        currentAnalysisSettings,
        pendingAnalysisSettings,
        launchSpec,
        baselineDriftSummary,
    } = input;
    const inventory = safeObject(state.latestSummary.inventory);
    const baseline = safeObject(state.latestSummary.baseline);
    const launch = launchSpec;
    return [
        detailNode("Workspace", state.folder.name),
        detailNode("Run ID", state.currentRunId),
        detailNode(
            "Analysis depth",
            currentAnalysisSettings ? currentAnalysisSettings.label : "unknown"
        ),
        detailNode(
            "Threshold profile",
            currentAnalysisSettings
                ? currentAnalysisSettings.thresholdSummary
                : "unknown"
        ),
        ...(pendingAnalysisSettings
            ? [
                detailNode(
                    "Next run",
                    `${pendingAnalysisSettings.label} · pending`
                ),
            ]
            : []),
        detailNode(
            "Freshness",
            state.stale ? `stale · ${state.staleReason}` : "current"
        ),
        detailNode("Files", number(inventory.files)),
        detailNode("Parsed lines", number(inventory.lines)),
        detailNode("Callables", number(inventory.functions)),
        detailNode("Classes", number(inventory.classes)),
        detailNode("Baseline", formatBaselineState(baseline)),
        // Same published fact, same shared reader as the triage markdown:
        // two surfaces deciding this separately is how they came to
        // disagree about one baseline.
        ...baselineProvenanceDetails(baseline).map((detail) =>
            detailNode(detail.label, detail.value)
        ),
        // Which launcher this extension resolved. Nothing about the
        // baseline can make it more or less true, so no baseline fact
        // gates it — only whether a runtime was started at all. The
        // session view already reports it on exactly those terms.
        ...(launch
            ? [detailNode("Runtime source", launchSpecOrigin(launch))]
            : []),
        detailNode(
            "Metrics baseline",
            formatBaselineState(state.latestSummary.metrics_baseline)
        ),
        detailNode("Baseline drift", baselineDriftSummary),
        detailNode("Cache", formatCacheSummary(state.latestSummary.cache)),
    ];
}

/**
 * Detail rows for the Session tree's "Local Server" section.
 *
 * @param {{
 *   connected: boolean,
 *   serverInfo: any,
 *   toolCount: number,
 *   launchSpec: any,
 * }} connectionInfo
 * @param {(label: string, description: string, command?: any) => any} detailNode
 * @returns {any[]}
 */
function buildServerSessionDetailNodes(connectionInfo, detailNode) {
    const launch = connectionInfo.launchSpec;
    return [
        detailNode("Connected", formatBooleanWord(connectionInfo.connected)),
        detailNode(
            "CodeClone version",
            connectionInfo.serverInfo ? connectionInfo.serverInfo.version : "unknown"
        ),
        detailNode("Available tools", number(connectionInfo.toolCount)),
        detailNode(
            "Runtime source",
            launch ? launchSpecOrigin(launch) : "not started"
        ),
        detailNode(
            "Launcher",
            launch ? `${launch.command} ${launch.args.join(" ")}`.trim() : "not started"
        ),
    ];
}

module.exports = {
    buildRunOverviewDetailNodes,
    buildServerSessionDetailNodes,
};
