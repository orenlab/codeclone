"use strict";

const {
    MINIMUM_SUPPORTED_CODECLONE_VERSION,
    PREVIEW_INSTALL_COMMAND,
} = require("./support");

const {
    capitalize,
    compactDecimal,
    decimal,
    formatBaselineTags,
    formatBaselineState,
    formatCoverageJoinLocation,
    formatCoverageJoinReviewSignal,
    formatKind,
    formatOverloadedModuleStatus,
    formatSecuritySurfaceLocation,
    formatSecuritySurfaceReviewSignal,
    formatSeverity,
    formatSourceKindSummary,
    humanizeIdentifier,
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
        "## Recommended install",
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
    const baseline = safeObject(summary.baseline);
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
    const baselineTags = formatBaselineTags(baseline);
    const lines = [
        "# CodeClone Production Triage",
        "",
        `- Run: \`${state.currentRunId || "n/a"}\``,
        `- Workspace: \`${state.folder.name}\``,
        `- Health: ${health.score || 0}/${health.grade || "?"} · ${healthScope} scope`,
        `- Baseline: ${formatBaselineState(baseline)}`,
        `- Focus: ${focus} · ${Number(triageFindings.outside_focus || 0)} outside focus`,
        `- Findings: ${findings.total || 0} total · ${findings.production || 0} production`,
        `- New findings: ${formatSourceKindSummary(findings.new_by_source_kind)}`,
        `- Source kinds: ${formatSourceKindSummary(triageFindings.by_source_kind)}`,
    ];
    if (baseline.compared_without_valid_baseline && baselineTags !== "unknown") {
        lines.push(`- Baseline tags: ${baselineTags}`);
    }
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
    const status = formatOverloadedModuleStatus(item);
    const lines = [
        "# Overloaded Module",
        "",
        `- Path: \`${item.path}\``,
        `- Module: \`${item.module}\``,
        `- Status: ${status}`,
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
    } else if (status !== "candidate") {
        lines.push(
            "",
            "## Review guidance",
            markdownBulletList([
                "This ranked row is report-only context, not an overloaded-module candidate.",
                "Use it as surrounding signal after reviewing candidate rows first.",
            ])
        );
    }
    return lines.join("\n");
}

function renderCoverageJoinMarkdown(item) {
    const location = formatCoverageJoinLocation(item);
    const coveragePercent =
        typeof item.coverage_permille === "number" && !Number.isNaN(item.coverage_permille)
            ? `${compactDecimal(item.coverage_permille / 10)}%`
            : "n/a";
    const guidance = [
        "Treat this as joined coverage review context, not as a clone or structural finding.",
    ];
    if (item.scope_gap_hotspot) {
        guidance.push(
            "The callable is in CodeClone analysis but not mapped from coverage.xml; verify whether tests exercise it under another path or add focused coverage."
        );
    } else if (item.coverage_hotspot) {
        guidance.push(
            "The callable is structurally risky and below the configured coverage threshold; inspect or add focused tests before refactoring."
        );
    }
    return [
        "# Coverage Join Review Item",
        "",
        `- Location: \`${location}\``,
        `- Function: \`${item.qualname || "(unknown)"}\``,
        `- Review signal: ${formatCoverageJoinReviewSignal(item)}`,
        `- Risk: ${item.risk || "low"}`,
        `- CC: ${number(item.cyclomatic_complexity || 0)}`,
        `- Coverage: ${coveragePercent}`,
        "",
        "## Review guidance",
        markdownBulletList(guidance),
    ].join("\n");
}

function renderSecuritySurfaceMarkdown(item) {
    const entry = safeObject(item);
    const location = formatSecuritySurfaceLocation(entry);
    const category = humanizeIdentifier(entry.category || "unknown");
    const capability = humanizeIdentifier(entry.capability || "unknown");
    const sourceKind = humanizeIdentifier(entry.source_kind || "unknown");
    const scope = humanizeIdentifier(entry.location_scope || "unknown");
    const classification = humanizeIdentifier(
        entry.classification_mode || "unknown"
    );
    const evidence = String(entry.evidence_symbol || "(unknown)");
    const reviewSignal = formatSecuritySurfaceReviewSignal(entry);
    const guidance = [
        "Treat this as a report-only boundary inventory entry, not as a vulnerability claim.",
        entry.location_scope === "module"
            ? "Trace the callable or entrypoint that consumes this module capability before refactoring it."
            : "Review the exact callable behavior at this trust boundary before refactoring it.",
    ];
    if (entry.scope_gap_hotspot) {
        guidance.push(
            "Coverage Join marks this callable as a scope gap, so validate the exercised path manually before change."
        );
    } else if (entry.coverage_hotspot) {
        guidance.push(
            "Coverage Join marks this callable as low coverage, so inspect or add boundary-focused tests before change."
        );
    } else if (entry.coverage_overlap) {
        guidance.push(
            "Coverage Join overlaps with this callable, so inspect the measured tests before changing boundary behavior."
        );
    }

    return [
        "# Security Surface",
        "",
        `- Location: \`${location}\``,
        `- Module: \`${entry.module || "unknown"}\``,
        `- Symbol: \`${entry.qualname || entry.module || "unknown"}\``,
        `- Category: ${category}`,
        `- Capability: ${capability}`,
        `- Evidence: \`${evidence}\``,
        `- Source kind: ${sourceKind}`,
        `- Scope: ${scope}`,
        `- Classification: ${classification}`,
        `- Review signal: ${reviewSignal}`,
        "",
        "## Review guidance",
        markdownBulletList(guidance),
    ].join("\n");
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function blastRadiusFileListSection(title, items, open) {
    if (items.length === 0) {
        return "";
    }
    const openAttr = open ? " open" : "";
    const listItems = items
        .map((f) => `<li>${escapeHtml(f)}</li>`)
        .join("");
    return `<details${openAttr}><summary>${escapeHtml(title)} (${items.length})</summary><ul class="file-list">${listItems}</ul></details>`;
}

function renderBlastRadiusMarkdown(payload, workspaceName) {
    const origin = safeArray(payload.origin);
    const direct = safeArray(payload.direct_dependents);
    const transitive = safeArray(payload.transitive_dependents);
    const cloneCohort = safeArray(payload.clone_cohort_members);
    const inCycle = safeArray(payload.in_dependency_cycle);
    const risk = safeObject(payload.structural_risk);
    const doNotTouch = safeArray(payload.do_not_touch);
    const reviewContext = safeArray(payload.review_context);
    const guardrails = safeArray(payload.guardrails);
    const radiusLevel = capitalize(String(payload.radius_level || "unknown"));

    const lines = [
        "# Blast Radius",
        "",
        `- Run: \`${payload.run_id || "unknown"}\``,
        `- Workspace: \`${workspaceName || "unknown"}\``,
        `- Depth: ${payload.depth || "direct"}`,
        `- Radius level: **${radiusLevel}**`,
        `- Origin: ${origin.length} files`,
        `- Direct dependents: ${direct.length}`,
        `- Transitive dependents: ${transitive.length}`,
        `- Clone cohort: ${cloneCohort.length}`,
    ];
    if (origin.length > 0) {
        lines.push(
            "",
            "## Origin files",
            markdownBulletList(origin.map((f) => `\`${f}\``))
        );
    }
    if (direct.length > 0) {
        lines.push(
            "",
            "## Direct dependents",
            markdownBulletList(direct.map((f) => `\`${f}\``))
        );
    }
    if (transitive.length > 0) {
        lines.push(
            "",
            "## Transitive dependents",
            markdownBulletList(transitive.map((f) => `\`${f}\``))
        );
    }
    if (cloneCohort.length > 0) {
        lines.push(
            "",
            "## Clone cohort members",
            markdownBulletList(cloneCohort.map((f) => `\`${f}\``))
        );
    }
    if (inCycle.length > 0) {
        lines.push(
            "",
            "## In dependency cycle",
            markdownBulletList(inCycle.map((f) => `\`${f}\``))
        );
    }
    const riskEntries = Object.entries(risk).filter(
        ([, paths]) => safeArray(paths).length > 0
    );
    if (riskEntries.length > 0) {
        lines.push("", "## Structural risk");
        for (const [key, paths] of riskEntries) {
            lines.push(
                "",
                `### ${humanizeIdentifier(key)}`,
                markdownBulletList(safeArray(paths).map((f) => `\`${f}\``))
            );
        }
    }
    if (doNotTouch.length > 0) {
        lines.push(
            "",
            "## Do not touch",
            markdownBulletList(
                doNotTouch.map(
                    (e) =>
                        `\`${safeObject(e).path}\` — ${safeObject(e).reason}`
                )
            )
        );
    }
    if (reviewContext.length > 0) {
        lines.push(
            "",
            "## Review context",
            markdownBulletList(
                reviewContext.map(
                    (e) =>
                        `\`${safeObject(e).path}\` — ${safeObject(e).reason}`
                )
            )
        );
    }
    if (guardrails.length > 0) {
        lines.push("", "## Guardrails", markdownBulletList(guardrails));
    }
    return lines.join("\n");
}

function renderBlastRadiusSvgHtml(payload, workspaceName, nonce) {
    const origin = safeArray(payload.origin);
    const direct = safeArray(payload.direct_dependents);
    const transitive = safeArray(payload.transitive_dependents);
    const cloneCohort = safeArray(payload.clone_cohort_members);
    const inCycle = safeArray(payload.in_dependency_cycle);
    const risk = safeObject(payload.structural_risk);
    const doNotTouch = safeArray(payload.do_not_touch);
    const reviewContext = safeArray(payload.review_context);
    const guardrails = safeArray(payload.guardrails);
    const radiusLevel = String(payload.radius_level || "unknown").toLowerCase();
    const depth = String(payload.depth || "direct");
    const runId = String(payload.run_id || "unknown");

    const hasDirect = direct.length > 0;
    const hasTransitive = transitive.length > 0;
    const hasClones = cloneCohort.length > 0;

    const cx = hasClones ? 260 : 300;
    const cy = 170;
    const originR = 50;
    const directR = hasDirect ? 105 : 0;
    const transitiveR = hasTransitive ? 155 : 0;
    const outerR = transitiveR || directR || originR;
    const svgWidth = hasClones ? 600 : 520;

    let svgContent = "";

    if (hasTransitive) {
        svgContent += `<circle cx="${cx}" cy="${cy}" r="${transitiveR}" class="ring ring-transitive"/>`;
        svgContent += `<text x="${cx}" y="${cy - transitiveR + 18}" class="ring-label">Transitive (${transitive.length})</text>`;
    }
    if (hasDirect) {
        svgContent += `<circle cx="${cx}" cy="${cy}" r="${directR}" class="ring ring-direct"/>`;
        svgContent += `<text x="${cx}" y="${cy - directR + 18}" class="ring-label">Direct (${direct.length})</text>`;
    }
    svgContent += `<circle cx="${cx}" cy="${cy}" r="${originR}" class="ring ring-origin"/>`;
    svgContent += `<text x="${cx}" y="${cy - 6}" class="ring-label origin-label">Origin</text>`;
    svgContent += `<text x="${cx}" y="${cy + 14}" class="ring-label">${origin.length} file${origin.length !== 1 ? "s" : ""}</text>`;

    if (hasClones) {
        const boxX = cx + outerR + 30;
        const boxW = Math.max(svgWidth - boxX - 10, 80);
        svgContent += `<rect x="${boxX}" y="${cy - 35}" width="${boxW}" height="70" rx="8" class="clone-box"/>`;
        svgContent += `<text x="${boxX + boxW / 2}" y="${cy - 8}" class="ring-label">Clone cohort</text>`;
        svgContent += `<text x="${boxX + boxW / 2}" y="${cy + 16}" class="ring-label clone-count">${cloneCohort.length}</text>`;
        svgContent += `<line x1="${cx + outerR}" y1="${cy}" x2="${boxX}" y2="${cy}" class="clone-line"/>`;
    }

    if (inCycle.length > 0) {
        svgContent += `<circle cx="${cx + 20}" cy="${cy + originR - 12}" r="6" class="cycle-marker"/>`;
        svgContent += `<text x="${cx + 32}" y="${cy + originR - 8}" class="legend-text" style="font-size:11px">${inCycle.length} in cycle</text>`;
    }

    const legendY = cy + outerR + 25;
    let legendX = 20;
    const legendItems = [{cssClass: "ring-origin", label: "Origin"}];
    if (hasDirect) {
        legendItems.push({cssClass: "ring-direct", label: "Direct"});
    }
    if (hasTransitive) {
        legendItems.push({cssClass: "ring-transitive", label: "Transitive"});
    }
    if (hasClones) {
        legendItems.push({cssClass: "clone-box", label: "Clones"});
    }

    for (const item of legendItems) {
        svgContent += `<rect x="${legendX}" y="${legendY}" width="12" height="12" rx="2" class="${item.cssClass}" style="stroke-width:1"/>`;
        svgContent += `<text x="${legendX + 18}" y="${legendY + 10}" class="legend-text">${escapeHtml(item.label)}</text>`;
        legendX += 18 + item.label.length * 7 + 16;
    }

    const svgHeight = legendY + 30;

    const svg = [
        `<svg viewBox="0 0 ${svgWidth} ${svgHeight}" xmlns="http://www.w3.org/2000/svg"`,
        ` role="img" aria-label="Blast radius: ${origin.length} origin, ${direct.length} direct, ${transitive.length} transitive, ${cloneCohort.length} clones">`,
        svgContent,
        "</svg>",
    ].join("");

    const detailSections = [];
    detailSections.push(blastRadiusFileListSection("Origin files", origin, true));
    if (hasDirect) {
        detailSections.push(blastRadiusFileListSection("Direct dependents", direct, false));
    }
    if (hasTransitive) {
        detailSections.push(blastRadiusFileListSection("Transitive dependents", transitive, false));
    }
    if (hasClones) {
        detailSections.push(blastRadiusFileListSection("Clone cohort members", cloneCohort, false));
    }
    if (inCycle.length > 0) {
        detailSections.push(blastRadiusFileListSection("In dependency cycle", inCycle, false));
    }

    const riskEntries = Object.entries(risk).filter(
        ([, paths]) => safeArray(paths).length > 0
    );
    if (riskEntries.length > 0) {
        let riskHtml = "<h2>Structural risk</h2>";
        for (const [key, paths] of riskEntries) {
            const riskClass = key.includes("complexity")
                ? "risk-high"
                : key.includes("coverage")
                    ? "risk-coverage"
                    : key.includes("overloaded")
                        ? "risk-overloaded"
                        : "risk-high";
            riskHtml += `<h3>${escapeHtml(humanizeIdentifier(key))}</h3><div class="risk-section">`;
            for (const p of safeArray(paths)) {
                riskHtml += `<div class="risk-item"><span class="risk-indicator ${riskClass}"></span><code>${escapeHtml(p)}</code></div>`;
            }
            riskHtml += "</div>";
        }
        detailSections.push(riskHtml);
    }

    if (doNotTouch.length > 0) {
        let html = `<h2>Do not touch (${doNotTouch.length})</h2>`;
        for (const entry of doNotTouch) {
            const e = safeObject(entry);
            html += `<div class="boundary-entry"><code class="boundary-path">${escapeHtml(e.path)}</code>`;
            html += `<span class="boundary-reason"> — ${escapeHtml(e.reason)}</span></div>`;
        }
        detailSections.push(html);
    }

    if (reviewContext.length > 0) {
        let html = `<h2>Review context (${reviewContext.length})</h2>`;
        for (const entry of reviewContext) {
            const e = safeObject(entry);
            html += `<div class="boundary-entry"><code class="boundary-path">${escapeHtml(e.path)}</code>`;
            html += `<span class="boundary-reason"> — ${escapeHtml(e.reason)}</span></div>`;
        }
        detailSections.push(html);
    }

    let guardrailsHtml = "";
    if (guardrails.length > 0) {
        const items = guardrails.map((g) => `<li>${escapeHtml(g)}</li>`).join("");
        guardrailsHtml = `<div class="guardrails"><h3>Guardrails</h3><ul>${items}</ul></div>`;
    }

    return [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">',
        `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">`,
        `<style nonce="${nonce}">`,
        "body{font-family:var(--vscode-font-family);color:var(--vscode-editor-foreground);background:var(--vscode-editor-background);padding:16px 24px;line-height:1.5;margin:0}",
        ".header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:4px}",
        "h1{font-size:1.6em;margin:0}",
        "h2{font-size:1.15em;margin:20px 0 8px;border-bottom:1px solid var(--vscode-widget-border,#444);padding-bottom:4px}",
        "h3{font-size:1em;margin:12px 0 4px}",
        ".badge{display:inline-block;padding:2px 10px;border-radius:10px;font-size:.85em;font-weight:600;text-transform:uppercase;letter-spacing:.03em}",
        ".badge-low{background:var(--vscode-charts-green,#388a34);color:#fff}",
        ".badge-medium{background:var(--vscode-charts-orange,#d18616);color:#fff}",
        ".badge-high{background:var(--vscode-charts-red,#e51400);color:#fff}",
        ".badge-unknown{background:var(--vscode-badge-background,#616161);color:var(--vscode-badge-foreground,#fff)}",
        ".meta{color:var(--vscode-descriptionForeground);font-size:.9em;margin-bottom:8px}",
        ".meta-item{margin-left:12px}",
        ".diagram{margin:16px 0;text-align:center}",
        ".diagram svg{max-width:600px;width:100%;height:auto}",
        ".ring{stroke-width:2}",
        ".ring-origin{fill:rgba(255,165,0,.12);stroke:var(--vscode-charts-orange,#d18616)}",
        ".ring-direct{fill:rgba(255,215,0,.08);stroke:var(--vscode-charts-yellow,#bf8803)}",
        ".ring-transitive{fill:rgba(70,130,220,.06);stroke:var(--vscode-charts-blue,#1e90ff)}",
        ".ring-label{fill:var(--vscode-editor-foreground);font-family:var(--vscode-font-family);font-size:13px;text-anchor:middle;dominant-baseline:middle}",
        ".origin-label{font-weight:600}",
        ".clone-box{fill:rgba(160,90,220,.10);stroke:var(--vscode-charts-purple,#652d90);stroke-width:2}",
        ".clone-line{stroke:var(--vscode-charts-purple,#652d90);stroke-width:1;stroke-dasharray:4 3;opacity:.5}",
        ".clone-count{font-weight:600;font-size:16px}",
        ".cycle-marker{fill:var(--vscode-charts-red,#e51400);opacity:.7}",
        ".legend-text{fill:var(--vscode-descriptionForeground);font-family:var(--vscode-font-family);font-size:11px;dominant-baseline:middle}",
        "details{margin:4px 0}",
        "summary{cursor:pointer;padding:4px 0;font-weight:500;user-select:none}",
        "summary:hover{color:var(--vscode-textLink-foreground)}",
        ".file-list{list-style:none;padding:0 0 0 16px;margin:4px 0}",
        ".file-list li{padding:2px 0;font-family:var(--vscode-editor-fontFamily,monospace);font-size:.9em}",
        '.file-list li::before{content:"\\2192  ";color:var(--vscode-descriptionForeground)}',
        ".boundary-entry{padding:2px 0 2px 16px;font-size:.9em}",
        ".boundary-path{font-family:var(--vscode-editor-fontFamily,monospace)}",
        ".boundary-reason{color:var(--vscode-descriptionForeground);margin-left:8px}",
        ".guardrails{margin:16px 0;padding:12px;border-left:3px solid var(--vscode-charts-orange,#d18616);background:var(--vscode-textBlockQuote-background,transparent)}",
        ".guardrails h3{margin:0 0 8px}",
        ".guardrails ul{margin:0;padding-left:20px}",
        ".guardrails li{padding:2px 0;font-size:.9em}",
        ".risk-section{margin:4px 0}",
        ".risk-item{display:flex;align-items:center;gap:8px;padding:2px 0 2px 16px}",
        ".risk-indicator{display:inline-block;width:8px;height:8px;border-radius:50%}",
        ".risk-high{background:var(--vscode-charts-red,#e51400)}",
        ".risk-coverage{background:var(--vscode-charts-orange,#d18616)}",
        ".risk-overloaded{background:var(--vscode-charts-purple,#652d90)}",
        "</style>",
        "</head>",
        "<body>",
        '<div class="header">',
        "<h1>Blast Radius</h1>",
        `<span class="badge badge-${radiusLevel}">${escapeHtml(capitalize(radiusLevel))}</span>`,
        "</div>",
        '<div class="meta">',
        `<span class="meta-item">Run: ${escapeHtml(runId)}</span>`,
        `<span class="meta-item">Depth: ${escapeHtml(depth)}</span>`,
        `<span class="meta-item">Workspace: ${escapeHtml(workspaceName)}</span>`,
        "</div>",
        `<div class="diagram">${svg}</div>`,
        detailSections.filter(Boolean).join("\n"),
        guardrailsHtml,
        "</body>",
        "</html>",
    ].join("\n");
}

module.exports = {
    markdownBulletList,
    renderBlastRadiusMarkdown,
    renderBlastRadiusSvgHtml,
    renderFindingMarkdown,
    renderCoverageJoinMarkdown,
    renderOverloadedModuleMarkdown,
    renderSecuritySurfaceMarkdown,
    renderHelpMarkdown,
    renderRemediationMarkdown,
    renderRestrictedModeMarkdown,
    renderSetupMarkdown,
    renderTriageMarkdown,
};
