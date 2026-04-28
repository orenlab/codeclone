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

    return {
        summary,
        triage,
        metricsSummary: metrics.summary || metrics,
        reviewedItems: arrayItems(reviewed.items),
        gitSnapshot,
    };
}

module.exports = {
    loadRunArtifacts,
};
