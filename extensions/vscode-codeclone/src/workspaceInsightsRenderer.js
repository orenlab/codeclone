"use strict";

const {safeArray, safeObject} = require("./formatters");

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/**
 * Audit payload_footprint_to_dict uses calls/tokens; session stats use call_count/total_tokens.
 *
 * @param {object | null | undefined} wf
 * @param {"tokens"|"calls"} kind
 */
function workflowMetric(wf, kind) {
    const item = safeObject(wf);
    if (!item) {
        return 0;
    }
    const value =
        kind === "tokens"
            ? item.tokens ?? item.total_tokens
            : item.calls ?? item.call_count;
    return value === null || value === undefined ? 0 : value;
}

/**
 * @param {object | null | undefined} footprint
 */
function footprintAggregateBanner(footprint) {
    const fp = safeObject(footprint);
    if (!fp) {
        return "";
    }
    const totalTokens = fp.total_tokens;
    const toolCalls = fp.tool_calls ?? 0;
    if (
        totalTokens === null ||
        totalTokens === undefined ||
        Number(toolCalls) <= 0
    ) {
        return "";
    }
    const parts = [
        `~${Number(totalTokens).toLocaleString("en-US")} total tokens`,
        `${toolCalls} tool calls`,
        fp.encoding ? String(fp.encoding) : null,
        fp.avg_tokens !== null && fp.avg_tokens !== undefined
            ? `avg ${fp.avg_tokens}`
            : null,
        fp.p95_tokens !== null && fp.p95_tokens !== undefined
            ? `p95 ${fp.p95_tokens}`
            : null,
        fp.max_tokens !== null && fp.max_tokens !== undefined
            ? `max ${fp.max_tokens}`
            : null,
    ].filter(Boolean);
    return `<p class="banner">${escapeHtml(parts.join(" · "))}</p>`;
}

/**
 * @param {number | null | undefined} seconds
 */
function formatAgeSeconds(seconds) {
    if (seconds === null || seconds === undefined || seconds < 0) {
        return "unknown";
    }
    if (seconds < 60) {
        return `${seconds}s ago`;
    }
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) {
        return `${minutes}m ago`;
    }
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    if (remainingMinutes) {
        return `${hours}h${remainingMinutes}m ago`;
    }
    return `${hours}h ago`;
}

/**
 * @param {number} seconds
 */
function formatDurationSeconds(seconds) {
    if (seconds <= 0) {
        return "expired";
    }
    if (seconds < 60) {
        return `${seconds}s`;
    }
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    if (remainingSeconds) {
        return `${minutes}m${remainingSeconds}s`;
    }
    return `${minutes}m`;
}

/**
 * @param {number | null | undefined} bytes
 */
function formatBytes(bytes) {
    if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) {
        return "unknown";
    }
    if (bytes < 1024) {
        return `${bytes} B`;
    }
    const units = ["KB", "MB", "GB", "TB"];
    let value = bytes / 1024;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }
    const rounded =
        value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
    return `${rounded} ${units[unitIndex]}`;
}

/**
 * @param {string} health
 */
function workspaceHealthClass(health) {
    return {
        idle: "health-idle",
        clean: "health-clean",
        active: "health-active",
        contested: "health-contested",
    }[health] || "health-active";
}

/**
 * @param {object} payload
 */
function sessionStatsBody(payload) {
    const root = safeObject(payload);
    const workspace = safeObject(root.workspace);
    const counts = safeObject(root.counts);
    const latest = safeObject(root.latest_run);
    const audit = safeObject(root.audit);
    const footprint = safeObject(root.token_footprint);
    const agents = safeArray(root.agents);
    const workflows = safeArray(root.top_workflows);
    const health = String(workspace.health || "unknown");

    const summaryRows = [
        ["Workspace health", `<span class="pill ${workspaceHealthClass(health)}">${escapeHtml(health)}</span>`],
        ["Live agents", escapeHtml(String(counts.live_agents ?? 0))],
        ["Active intents", escapeHtml(String(counts.active_intents ?? 0))],
        ["Visible intents", escapeHtml(String(counts.visible_intents ?? 0))],
        ["Stale / expired / recoverable", `${escapeHtml(String(counts.stale ?? 0))} / ${escapeHtml(String(counts.expired ?? 0))} / ${escapeHtml(String(counts.recoverable ?? 0))}`],
    ];

    if (workspace.intent_registry_backend) {
        summaryRows.push([
            "Intent registry",
            `${escapeHtml(String(workspace.intent_registry_backend))} (${escapeHtml(String(workspace.intent_registry_storage || "—"))})`,
        ]);
    }
    if (audit.enabled) {
        summaryRows.push([
            "Audit storage",
            escapeHtml(String(audit.storage || "enabled")),
        ]);
    }

    let latestHtml = '<p class="muted">No cached report in .codeclone/report.json.</p>';
    if (latest.cache_present && latest.run_id) {
        const age = formatAgeSeconds(
            typeof latest.age_seconds === "number" ? latest.age_seconds : null
        );
        const parts = [
            `<code>${escapeHtml(String(latest.run_id))}</code>`,
            escapeHtml(age),
        ];
        if (latest.health !== null && latest.health !== undefined) {
            parts.push(`health=${escapeHtml(String(latest.health))}`);
        }
        if (latest.findings !== null && latest.findings !== undefined) {
            parts.push(`findings=${escapeHtml(String(latest.findings))}`);
        }
        if (latest.files !== null && latest.files !== undefined) {
            parts.push(`${escapeHtml(String(latest.files))} files indexed`);
        }
        latestHtml = `<p>${parts.join(" · ")}</p>`;
    }

    const liveAgents = agents.filter((raw) => safeObject(raw)?.alive);
    let agentsHtml = `<p class="muted">${liveAgents.length === 0 ? "No live agent processes with visible intents." : ""}</p>`;
    if (liveAgents.length > 0) {
        const rows = liveAgents
            .map((raw) => {
                const agent = safeObject(raw);
                const intents = safeArray(agent.intents);
                const intentLines = intents
                    .map((intentRaw) => {
                        const intent = safeObject(intentRaw);
                        const files = safeArray(intent.allowed_files)
                            .slice(0, 2)
                            .map((file) => `<code>${escapeHtml(String(file))}</code>`)
                            .join(", ");
                        const extra =
                            safeArray(intent.allowed_files).length > 2
                                ? ` (+${safeArray(intent.allowed_files).length - 2} more)`
                                : "";
                        return [
                            "<tr>",
                            `<td><code>${escapeHtml(String(intent.intent_id || ""))}</code></td>`,
                            `<td>${escapeHtml(String(intent.status || ""))}</td>`,
                            `<td>${escapeHtml(String(intent.ownership || ""))}</td>`,
                            `<td>${escapeHtml(String(intent.scope_file_count ?? 0))}</td>`,
                            `<td>${escapeHtml(formatDurationSeconds(Number(intent.lease_remaining_seconds ?? 0)))}</td>`,
                            `<td>${files}${extra}</td>`,
                            "</tr>",
                        ].join("");
                    })
                    .join("");
                const label = escapeHtml(String(agent.label || "unknown"));
                const started = formatAgeSeconds(
                    Math.max(0, Math.floor(Date.now() / 1000) - Number(agent.start_epoch || 0))
                );
                return [
                    `<h3>PID ${escapeHtml(String(agent.pid))} · ${label}</h3>`,
                    `<p class="muted">Started ${escapeHtml(started)}</p>`,
                    '<table class="data-table"><thead><tr>',
                    "<th>Intent</th><th>Status</th><th>Ownership</th><th>Scope</th><th>Lease</th><th>Allowed files</th>",
                    `</tr></thead><tbody>${intentLines}</tbody></table>`,
                ].join("");
            })
            .join("");
        agentsHtml = rows;
    }

    let workflowsHtml = "";
    if (workflows.length > 0) {
        const wfRows = workflows
            .map((raw) => {
                const wf = safeObject(raw);
                const name = `${wf.workflow_kind || "workflow"}:${wf.workflow_id || "-"}`;
                const tokens = workflowMetric(wf, "tokens");
                const calls = workflowMetric(wf, "calls");
                return [
                    "<tr>",
                    `<td>${escapeHtml(name)}</td>`,
                    `<td class="num">~${escapeHtml(String(tokens))}</td>`,
                    `<td class="num">${escapeHtml(String(calls))}</td>`,
                    `<td>${escapeHtml(String(wf.agent_label || "—"))}</td>`,
                    "</tr>",
                ].join("");
            })
            .join("");
        workflowsHtml = [
            "<h2>Top workflows (audit footprint)</h2>",
            '<table class="data-table"><thead><tr>',
            "<th>Workflow</th><th>Tokens</th><th>Calls</th><th>Agent</th>",
            `</tr></thead><tbody>${wfRows}</tbody></table>`,
        ].join("");
    }

    let footprintHtml = "";
    if (footprint.total_tokens !== null && footprint.total_tokens !== undefined) {
        const calls = footprint.tool_calls ?? 0;
        if (Number(calls) > 0) {
            footprintHtml = `<p class="banner">~${escapeHtml(String(footprint.total_tokens))} estimated tokens in retention (${escapeHtml(String(footprint.encoding || "unknown"))}, ${escapeHtml(String(calls))} tool calls)</p>`;
        }
    }

    const summaryTable = [
        '<table class="summary-table"><tbody>',
        ...summaryRows.map(
            ([label, value]) =>
                `<tr><th>${escapeHtml(label)}</th><td>${value}</td></tr>`
        ),
        "</tbody></table>",
    ].join("");

    return [
        summaryTable,
        footprintHtml,
        "<h2>Latest cached run</h2>",
        latestHtml,
        "<h2>Live agents and intents</h2>",
        agentsHtml,
        workflowsHtml,
    ].join("\n");
}

/**
 * @param {object} payload
 */
function auditTrailBody(payload) {
    const root = safeObject(payload);
    const status = String(root.status || "ok");
    const message = root.message ? String(root.message) : "";
    const database = safeObject(root.database);
    const counts = safeObject(root.counts);
    const timeRange = safeObject(root.time_range);
    const tokenSummary = safeObject(root.token_summary);
    const footprint = safeObject(root.payload_footprint);
    const events = safeArray(root.events);

    let banner = "";
    if (status !== "ok") {
        banner = `<div class="banner banner-warn" role="alert"><strong>${escapeHtml(status)}</strong>${message ? `: ${escapeHtml(message)}` : ""}</div>`;
    }

    const metaRows = [];
    if (database.path) {
        metaRows.push(["Database", `<code>${escapeHtml(String(database.path))}</code>`]);
    }
    if (database.size_bytes !== null && database.size_bytes !== undefined) {
        metaRows.push(["Size", escapeHtml(formatBytes(Number(database.size_bytes)))]);
    }
    if (database.retention_days !== null && database.retention_days !== undefined) {
        metaRows.push(["Retention", `${escapeHtml(String(database.retention_days))} days`]);
    }
    metaRows.push(
        ["Total events", escapeHtml(String(counts.total_events ?? 0))],
        [
            "By kind",
            `intents ${escapeHtml(String(counts.intent_events ?? 0))} · contracts ${escapeHtml(String(counts.contract_events ?? 0))} · receipts ${escapeHtml(String(counts.receipt_events ?? 0))} · violations ${escapeHtml(String(counts.violation_events ?? 0))}`,
        ]
    );
    if (timeRange.oldest_event_utc || timeRange.latest_event_utc) {
        metaRows.push([
            "Time range",
            `${escapeHtml(String(timeRange.oldest_event_utc || "—"))} → ${escapeHtml(String(timeRange.latest_event_utc || "—"))}`,
        ]);
    }
    if (
        tokenSummary.total_estimated_tokens !== null &&
        tokenSummary.total_estimated_tokens !== undefined
    ) {
        metaRows.push([
            "Token estimate",
            `~${escapeHtml(String(tokenSummary.total_estimated_tokens))} (${escapeHtml(String(tokenSummary.token_encoding || "unknown"))}, ${escapeHtml(String(tokenSummary.token_event_count ?? 0))} events)`,
        ]);
    }

    const metaTable = [
        '<table class="summary-table"><tbody>',
        ...metaRows.map(
            ([label, value]) =>
                `<tr><th>${escapeHtml(label)}</th><td>${value}</td></tr>`
        ),
        "</tbody></table>",
    ].join("");

    let footprintHtml = "";
    if (footprint && Object.keys(footprint).length > 0) {
        const aggregate = footprintAggregateBanner(footprint);
        const top = safeArray(footprint.top_workflows);
        const sections = [];
        if (aggregate || top.length > 0) {
            sections.push("<h2>Payload footprint (retention window)</h2>");
            if (aggregate) {
                sections.push(aggregate);
            }
        }
        if (top.length > 0) {
            const rows = top
                .map((raw) => {
                    const wf = safeObject(raw);
                    const tokens = workflowMetric(wf, "tokens");
                    const calls = workflowMetric(wf, "calls");
                    return [
                        "<tr>",
                        `<td>${escapeHtml(`${wf.workflow_kind || "workflow"}:${wf.workflow_id || "-"}`)}</td>`,
                        `<td class="num">~${escapeHtml(String(tokens))}</td>`,
                        `<td class="num">${escapeHtml(String(calls))}</td>`,
                        "</tr>",
                    ].join("");
                })
                .join("");
            sections.push(
                '<table class="data-table"><thead><tr><th>Workflow</th><th>Tokens</th><th>Calls</th></tr></thead>',
                `<tbody>${rows}</tbody></table>`
            );
        }
        footprintHtml = sections.join("\n");
    }

    let eventsHtml = '<p class="muted">No recent events in this window.</p>';
    if (events.length > 0) {
        const rows = events
            .map((raw) => {
                const event = safeObject(raw);
                const summary = escapeHtml(
                    String(event.summary || event.event_type || "event")
                );
                const meta = [
                    event.created_at_utc
                        ? escapeHtml(String(event.created_at_utc))
                        : "",
                    event.severity ? escapeHtml(String(event.severity)) : "",
                    event.intent_id
                        ? `<code>${escapeHtml(String(event.intent_id))}</code>`
                        : "",
                    event.agent_label ? escapeHtml(String(event.agent_label)) : "",
                ]
                    .filter(Boolean)
                    .join(" · ");
                const tokens =
                    event.estimated_tokens !== null &&
                    event.estimated_tokens !== undefined
                        ? ` ~${escapeHtml(String(event.estimated_tokens))} tok`
                        : "";
                return [
                    "<tr>",
                    `<td>${summary}</td>`,
                    `<td>${escapeHtml(String(event.event_type || ""))}</td>`,
                    `<td class="meta-cell">${meta}${tokens}</td>`,
                    "</tr>",
                ].join("");
            })
            .join("");
        eventsHtml = [
            `<h2>Recent events (${events.length})</h2>`,
            '<table class="data-table events-table"><thead><tr>',
            "<th>Summary</th><th>Type</th><th>Details</th>",
            `</tr></thead><tbody>${rows}</tbody></table>`,
        ].join("");
    }

    return [banner, metaTable, footprintHtml, eventsHtml].join("\n");
}

const SHARED_STYLES = [
    "body{font-family:var(--vscode-font-family);color:var(--vscode-editor-foreground);background:var(--vscode-editor-background);padding:16px 22px;line-height:1.5;margin:0}",
    ".header{margin-bottom:14px}",
    "h1{font-size:1.35em;margin:0 0 4px}",
    "h2{font-size:1.05em;margin:20px 0 8px}",
    "h3{font-size:.95em;margin:14px 0 6px}",
    ".meta{color:var(--vscode-descriptionForeground);font-size:.9em}",
    ".banner{margin:12px 0;padding:10px 12px;border-radius:6px;background:var(--vscode-textBlockQuote-background);border-left:3px solid var(--vscode-textLink-foreground)}",
    ".banner-warn{border-left-color:var(--vscode-inputValidation-warningBorder);background:var(--vscode-inputValidation-warningBackground)}",
    ".summary-table{width:100%;border-collapse:collapse;margin:8px 0 16px}",
    ".summary-table th{text-align:left;padding:6px 12px 6px 0;color:var(--vscode-descriptionForeground);font-weight:600;vertical-align:top;white-space:nowrap;width:180px}",
    ".summary-table td{padding:6px 0}",
    ".data-table{width:100%;border-collapse:collapse;font-size:.92em;margin:8px 0}",
    ".data-table th,.data-table td{border-bottom:1px solid var(--vscode-widget-border,#444);padding:6px 8px;text-align:left}",
    ".data-table th{color:var(--vscode-descriptionForeground);font-weight:600}",
    ".data-table .num{text-align:right;font-variant-numeric:tabular-nums}",
    ".meta-cell{color:var(--vscode-descriptionForeground);font-size:.88em}",
    ".pill{display:inline-block;padding:2px 10px;border-radius:10px;font-size:.85em;font-weight:600;text-transform:uppercase;letter-spacing:.03em}",
    ".health-idle{background:var(--vscode-badge-background);color:var(--vscode-badge-foreground)}",
    ".health-clean{background:var(--vscode-testing-iconPassed,#2ea043);color:#fff}",
    ".health-active{background:var(--vscode-charts-blue,#1e90ff);color:#fff}",
    ".health-contested{background:var(--vscode-inputValidation-warningBorder,#cca700);color:#000}",
    ".muted{color:var(--vscode-descriptionForeground);font-style:italic}",
    "code{font-family:var(--vscode-editor-font-family)}",
].join("");

/**
 * @param {object} payload
 * @param {string} workspaceName
 * @param {string} nonce
 */
function renderSessionStatsHtml(payload, workspaceName, nonce) {
    const root = String(safeObject(payload)?.workspace?.root || "");
    const body = sessionStatsBody(payload);
    return [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">',
        `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">`,
        `<style nonce="${nonce}">${SHARED_STYLES}</style>`,
        "</head>",
        "<body>",
        '<header class="header">',
        "<h1>Workspace Session Stats</h1>",
        `<p class="meta">Workspace: ${escapeHtml(workspaceName)} · mirrors <code>codeclone . --session-stats</code></p>`,
        root ? `<p class="meta"><code>${escapeHtml(root)}</code></p>` : "",
        "</header>",
        body,
        '<footer class="meta"><p>IDE-only MCP tool — not exposed to agent clients on the default launcher.</p></footer>',
        "</body>",
        "</html>",
    ].join("\n");
}

/**
 * @param {object} payload
 * @param {string} workspaceName
 * @param {string} nonce
 */
function renderAuditTrailHtml(payload, workspaceName, nonce) {
    const body = auditTrailBody(payload);
    return [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">',
        `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">`,
        `<style nonce="${nonce}">${SHARED_STYLES}</style>`,
        "</head>",
        "<body>",
        '<header class="header">',
        "<h1>Controller Audit Trail</h1>",
        `<p class="meta">Workspace: ${escapeHtml(workspaceName)} · mirrors <code>codeclone . --audit</code></p>`,
        "</header>",
        body,
        '<footer class="meta"><p>Requires audit_enabled=true in pyproject.toml. IDE-only MCP tool.</p></footer>',
        "</body>",
        "</html>",
    ].join("\n");
}

/**
 * @param {object} payload
 */
function renderSessionStatsMarkdown(payload) {
    const root = safeObject(payload);
    const workspace = safeObject(root.workspace);
    const counts = safeObject(root.counts);
    const latest = safeObject(root.latest_run);
    const lines = [
        "# Workspace session stats",
        "",
        `- Workspace health: **${workspace.health || "unknown"}**`,
        `- Live agents: ${counts.live_agents ?? 0}`,
        `- Active intents: ${counts.active_intents ?? 0}`,
        `- Visible intents: ${counts.visible_intents ?? 0}`,
        `- Stale / expired / recoverable: ${counts.stale ?? 0} / ${counts.expired ?? 0} / ${counts.recoverable ?? 0}`,
    ];
    if (latest.cache_present && latest.run_id) {
        lines.push(
            `- Latest run: \`${latest.run_id}\` (${formatAgeSeconds(latest.age_seconds)})`
        );
    } else {
        lines.push("- Latest run: none (no cached report)");
    }
    const agents = safeArray(root.agents).filter((raw) => safeObject(raw)?.alive);
    if (agents.length > 0) {
        lines.push("", "## Live agents");
        for (const raw of agents) {
            const agent = safeObject(raw);
            lines.push(`- PID ${agent.pid} (${agent.label || "unknown"})`);
            for (const intentRaw of safeArray(agent.intents)) {
                const intent = safeObject(intentRaw);
                lines.push(
                    `  - \`${intent.intent_id}\` ${intent.status} · ${intent.ownership} · lease ${formatDurationSeconds(Number(intent.lease_remaining_seconds ?? 0))}`
                );
            }
        }
    }
    return lines.join("\n");
}

/**
 * @param {object} payload
 */
function renderAuditTrailMarkdown(payload) {
    const root = safeObject(payload);
    const status = String(root.status || "ok");
    const counts = safeObject(root.counts);
    const lines = [
        "# Controller audit trail",
        "",
        `- Status: **${status}**`,
        root.message ? `- Message: ${root.message}` : "",
        `- Total events: ${counts.total_events ?? 0}`,
        `- Intent / contract / receipt / violation: ${counts.intent_events ?? 0} / ${counts.contract_events ?? 0} / ${counts.receipt_events ?? 0} / ${counts.violation_events ?? 0}`,
    ].filter(Boolean);
    const events = safeArray(root.events);
    if (events.length > 0) {
        lines.push("", "## Recent events");
        for (const raw of events.slice(0, 20)) {
            const event = safeObject(raw);
            lines.push(
                `- ${event.created_at_utc || "?"} **${event.event_type || "event"}** — ${event.summary || ""}`
            );
        }
    }
    return lines.join("\n");
}

module.exports = {
    escapeHtml,
    workflowMetric,
    footprintAggregateBanner,
    formatAgeSeconds,
    formatDurationSeconds,
    formatBytes,
    renderSessionStatsHtml,
    renderAuditTrailHtml,
    renderSessionStatsMarkdown,
    renderAuditTrailMarkdown,
    sessionStatsBody,
    auditTrailBody,
};
