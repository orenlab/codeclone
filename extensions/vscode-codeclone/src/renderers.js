"use strict";

const {
    MINIMUM_SUPPORTED_CODECLONE_VERSION,
    PREVIEW_INSTALL_COMMAND,
} = require("./support");

const {
    capitalize,
    compactDecimal,
    decimal,
    formatKind,
    formatSeverity,
    formatSourceKindSummary,
    normalizeLocations,
    number,
    safeArray,
    safeObject,
} = require("./formatters");

function markdownBulletList(values) {
    return values.map((value) => `- ${value}`).join("\n");
}

function renderHelpMarkdown(topic, payload) {
    const titleTopic = String(topic || "").replace(/_/g, " ");
    const lines = [
        `# CodeClone MCP Help: ${titleTopic}`,
        "",
        payload.summary || "",
        "",
        "## Key points",
        markdownBulletList(safeArray(payload.key_points)),
        "",
        "## Recommended tools",
        markdownBulletList(safeArray(payload.recommended_tools).map((tool) => `\`${tool}\``)),
    ];
    const warnings = safeArray(payload.warnings);
    if (warnings.length > 0) {
        lines.push("", "## Warnings", markdownBulletList(warnings));
    }
    const antiPatterns = safeArray(payload.anti_patterns);
    if (antiPatterns.length > 0) {
        lines.push("", "## Anti-patterns", markdownBulletList(antiPatterns));
    }
    const docLinks = safeArray(payload.doc_links);
    if (docLinks.length > 0) {
        lines.push(
            "",
            "## Docs",
            markdownBulletList(
                docLinks.map((entry) => `[${entry.title}](${entry.url})`)
            )
        );
    }
    return lines.join("\n");
}

function renderSetupMarkdown() {
    return [
        "# Set Up CodeClone MCP",
        "",
        "The VS Code extension needs a local `codeclone-mcp` launcher.",
        "",
        `Minimum supported CodeClone version: \`${MINIMUM_SUPPORTED_CODECLONE_VERSION}\``,
        "",
        "## Recommended install for the preview extension",
        "",
        "```bash",
        PREVIEW_INSTALL_COMMAND,
        "```",
        "",
        "## Verify the launcher",
        "",
        "```bash",
        "codeclone-mcp --help",
        "```",
        "",
        "## If CodeClone lives in a custom environment",
        "",
        "- Set `codeclone.mcp.command` to the launcher you want VS Code to use.",
        "- Set `codeclone.mcp.args` if that launcher needs extra arguments.",
        "- In the CodeClone repository itself, the extension can also fall back to `uv run codeclone-mcp`.",
        "",
        "## What the extension expects",
        "",
        "- A local `codeclone-mcp` command, or an explicit custom launcher in settings.",
        "- MCP support installed, not only the base `codeclone` package.",
        `- CodeClone ${MINIMUM_SUPPORTED_CODECLONE_VERSION} or newer.`,
        "",
        "Once that is ready, run `Analyze Workspace` again.",
    ].join("\n");
}

function renderRestrictedModeMarkdown(topic) {
    return [
        "# CodeClone: Restricted Mode",
        "",
        "The workspace is not trusted, so CodeClone keeps local analysis and the local MCP server offline.",
        "",
        topic
            ? `Live MCP help for \`${topic}\` becomes available after workspace trust is granted.`
            : "Live MCP help topics become available after workspace trust is granted.",
        "",
        "## What you can do safely right now",
        "",
        "- Review installation and setup guidance.",
        "- Inspect the extension surface and onboarding text.",
        "- Grant workspace trust when you are ready to enable local analysis.",
        "",
        "## Next step",
        "",
        "Run `Manage Workspace Trust`, then open the help topic again.",
    ].join("\n");
}

function renderFindingMarkdown(payload) {
    const remediation = safeObject(payload.remediation);
    const locations = normalizeLocations(payload.locations);
    const spread = safeObject(payload.spread);
    const lines = [
        `# ${formatKind(payload.kind)}`,
        "",
        `- Finding id: \`${payload.id}\``,
        `- Severity: ${formatSeverity(payload.severity)}`,
        `- Scope: ${payload.scope || "unknown"}`,
        `- Priority: ${compactDecimal(payload.priority)}`,
        `- Count: ${payload.count || 0}`,
        `- Spread: ${spread.files || 0} files / ${spread.functions || 0} functions`,
    ];
    if (locations.length > 0) {
        lines.push(
            "",
            "## Locations",
            markdownBulletList(
                locations.map((location) => {
                    const range =
                        location.line !== null && location.end_line !== null
                            ? `${location.line}-${location.end_line}`
                            : location.line !== null
                                ? `${location.line}`
                                : "?";
                    const symbol = location.symbol ? ` — \`${location.symbol}\`` : "";
                    return `\`${location.path}:${range}\`${symbol}`;
                })
            )
        );
    }
    if (Object.keys(remediation).length > 0) {
        lines.push("", "## Remediation");
        if (remediation.shape) {
            lines.push("", remediation.shape);
        }
        if (remediation.why_now) {
            lines.push("", `Why now: ${remediation.why_now}`);
        }
        if (remediation.effort || remediation.risk) {
            lines.push(
                "",
                `Effort: ${remediation.effort || "unknown"} · Risk: ${remediation.risk || "unknown"}`
            );
        }
        const steps = safeArray(remediation.steps);
        if (steps.length > 0) {
            lines.push("", "### Steps", markdownBulletList(steps));
        }
    }
    return lines.join("\n");
}

function renderRemediationMarkdown(payload) {
    const remediation = safeObject(payload.remediation);
    const lines = [
        `# Remediation: \`${payload.finding_id}\``,
        "",
    ];
    if (remediation.shape) {
        lines.push(remediation.shape, "");
    }
    lines.push(
        `- Effort: ${remediation.effort || "unknown"}`,
        `- Risk: ${remediation.risk || "unknown"}`
    );
    if (remediation.why_now) {
        lines.push("", `Why now: ${remediation.why_now}`);
    }
    const steps = safeArray(remediation.steps);
    if (steps.length > 0) {
        lines.push("", "## Steps", markdownBulletList(steps));
    }
    return lines.join("\n");
}

function renderTriageMarkdown(state) {
    const summary = safeObject(state.latestSummary);
    const triage = safeObject(state.latestTriage);
    const health = safeObject(summary.health);
    const findings = safeObject(summary.findings);
    const triageFindings = safeObject(triage.findings);
    const topHotspots = safeObject(triage.top_hotspots);
    const topSuggestions = safeObject(triage.top_suggestions);
    const focus = capitalize(String(triage.focus || "production").replace(/_/g, " "));
    const healthScope = capitalize(
        String(summary.health_scope || triage.health_scope || "repository").replace(
            /_/g,
            " "
        )
    );
    const items = safeArray(topHotspots.items);
    const suggestions = safeArray(topSuggestions.items);
    const lines = [
        "# CodeClone Production Triage",
        "",
        `- Run: \`${state.currentRunId || "n/a"}\``,
        `- Workspace: \`${state.folder.name}\``,
        `- Health: ${health.score || 0}/${health.grade || "?"} · ${healthScope} scope`,
        `- Focus: ${focus} · ${Number(triageFindings.outside_focus || 0)} outside focus`,
        `- Findings: ${findings.total || 0} total · ${findings.production || 0} production`,
        `- New findings: ${formatSourceKindSummary(findings.new_by_source_kind)}`,
        `- Source kinds: ${formatSourceKindSummary(triageFindings.by_source_kind)}`,
    ];
    if (items.length > 0) {
        lines.push(
            "",
            "## Top production hotspots",
            markdownBulletList(
                items.map(
                    (item) =>
                        `\`${item.id}\` — ${formatKind(item.kind)} · ${formatSeverity(
                            item.severity
                        )} · ${item.scope || "unknown"} · priority ${compactDecimal(item.priority)}`
                )
            )
        );
    } else {
        lines.push("", "## Top production hotspots", "", "None.");
    }
    if (suggestions.length > 0) {
        lines.push(
            "",
            "## Top suggestions",
            markdownBulletList(
                suggestions.map((item) => `\`${item.id}\` — ${item.summary || "Suggestion"}`)
            )
        );
    }
    return lines.join("\n");
}

function renderOverloadedModuleMarkdown(item) {
    const reasons = safeArray(item.candidate_reasons);
    const lines = [
        "# Overloaded Module Candidate",
        "",
        `- Path: \`${item.path}\``,
        `- Module: \`${item.module}\``,
        `- Source kind: ${item.source_kind || "unknown"}`,
        `- Score: ${decimal(item.score)}`,
        `- LOC: ${number(item.loc)}`,
        `- Callables: ${item.callable_count || 0}`,
        `- Complexity total / max: ${item.complexity_total || 0} / ${item.complexity_max || 0}`,
        `- Fan-in / fan-out: ${item.fan_in || 0} / ${item.fan_out || 0}`,
        `- Total dependencies: ${item.total_deps || 0}`,
        `- Import edges / reimport edges: ${item.import_edges || 0} / ${item.reimport_edges || 0}`,
        `- Reimport ratio: ${decimal(item.reimport_ratio)}`,
        `- Instability: ${decimal(item.instability)}`,
        `- Hub balance: ${decimal(item.hub_balance)}`,
    ];
    if (reasons.length > 0) {
        lines.push("", "## Candidate reasons", markdownBulletList(reasons));
    }
    return lines.join("\n");
}

module.exports = {
    markdownBulletList,
    renderFindingMarkdown,
    renderOverloadedModuleMarkdown,
    renderHelpMarkdown,
    renderRemediationMarkdown,
    renderRestrictedModeMarkdown,
    renderSetupMarkdown,
    renderTriageMarkdown,
};
