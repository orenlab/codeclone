"use strict";

const {captureWorkspaceGitSnapshot} = require("./runtime");

function arrayItems(value) {
    return Array.isArray(value) ? value : [];
}

async function loadRunArtifacts(
    client,
    folder,
    runId,
    captureGitSnapshot = captureWorkspaceGitSnapshot
) {
    const [summary, triage, metrics, reviewed, gitSnapshot] = await Promise.all([
        client.callTool("get_run_summary", {
            run_id: runId,
        }),
        client.callTool("get_production_triage", {
            run_id: runId,
            max_hotspots: 5,
            max_suggestions: 5,
        }),
        client.callTool("get_report_section", {
            run_id: runId,
            section: "metrics",
        }),
        client.callTool("list_reviewed_findings", {
            run_id: runId,
        }),
        captureGitSnapshot(folder),
    ]);

    const metricsSummary = {...(metrics.summary || metrics)};
    if (summary.coverage_join && !metricsSummary.coverage_join) {
        metricsSummary.coverage_join = summary.coverage_join;
    }
    if (summary.security_surfaces && !metricsSummary.security_surfaces) {
        metricsSummary.security_surfaces = summary.security_surfaces;
    }

    return {
        summary,
        triage,
        metricsSummary,
        reviewedItems: arrayItems(reviewed.items),
        gitSnapshot,
    };
}

module.exports = {
    loadRunArtifacts,
};
