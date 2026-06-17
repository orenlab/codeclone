"use strict";

const {safeArray, safeObject} = require("./formatters");
const {SHARED_STYLES, escapeHtml, formatDurationSeconds} = require("./workspaceInsightsRenderer");

/**
 * @param {unknown} value
 */
function pillClassForOutcome(value) {
    const outcome = String(value || "").toLowerCase();
    if (outcome === "accepted" || outcome === "accepted_with_external_changes") {
        return "pill pill-ok";
    }
    if (outcome === "violated" || outcome === "blocked") {
        return "pill pill-bad";
    }
    return "pill pill-warn";
}

/**
 * @param {unknown} value
 */
function pillClassForSeverity(value) {
    return String(value) === "error" ? "pill pill-bad" : "pill pill-warn";
}

/**
 * @param {object | null | undefined} status
 */
function statusSection(status) {
    const root = safeObject(status);
    if (!root) {
        return '<p class="muted">No trajectory status available.</p>';
    }
    const latest = safeObject(root.latest_projection);
    const latestText =
        latest && latest.finished_at_utc
            ? `${latest.finished_at_utc} · ${latest.workflows_seen ?? 0} workflows · +${latest.created ?? 0}/~${latest.updated ?? 0}`
            : "none";
    return [
        '<table class="summary-table">',
        "<tbody>",
        `<tr><th>Stored trajectories</th><td>${escapeHtml(String(root.trajectory_count ?? 0))}</td></tr>`,
        `<tr><th>Latest projection</th><td>${escapeHtml(latestText)}</td></tr>`,
        "</tbody>",
        "</table>",
    ].join("\n");
}

/**
 * @param {object | null | undefined} agents
 */
function agentsSection(agents) {
    const root = safeObject(agents);
    if (!root) {
        return "";
    }
    const rows = safeArray(root.agents);
    if (rows.length === 0) {
        return '<h2>Agents</h2><p class="muted">No agent-labeled trajectories yet. Rebuild trajectories after audit events include agent_label.</p>';
    }
    const body = rows
        .map((raw) => {
            const row = safeObject(raw);
            if (!row) {
                return "";
            }
            return [
                "<tr>",
                `<td><code>${escapeHtml(String(row.agent_label || "?"))}</code></td>`,
                `<td class="num">${escapeHtml(String(row.trajectory_count ?? 0))}</td>`,
                `<td class="num">${escapeHtml(String(row.intent_count ?? 0))}</td>`,
                `<td class="num">${escapeHtml(String(row.failed_outcome_count ?? 0))}</td>`,
                `<td class="num">${escapeHtml(String(row.anomaly_count ?? 0))}</td>`,
                `<td class="num">${escapeHtml(String(row.incident_total ?? 0))}</td>`,
                "</tr>",
            ].join("");
        })
        .join("\n");
    return [
        "<h2>Agents</h2>",
        `<p class="meta">${escapeHtml(String(root.agent_count ?? 0))} agents · ${escapeHtml(String(root.trajectory_count ?? 0))} trajectories · ${escapeHtml(String(root.unlabeled_trajectory_count ?? 0))} unlabeled</p>`,
        '<table class="data-table">',
        "<thead><tr><th>Agent</th><th class=\"num\">Trajectories</th><th class=\"num\">Intents</th><th class=\"num\">Failed</th><th class=\"num\">Anomalies</th><th class=\"num\">Incidents</th></tr></thead>",
        `<tbody>${body}</tbody>`,
        "</table>",
    ].join("\n");
}

/**
 * @param {object | null | undefined} anomalies
 */
function anomaliesSection(anomalies) {
    const root = safeObject(anomalies);
    if (!root) {
        return "";
    }
    const summary = safeObject(root.summary);
    const banner = summary
        ? `<p class="banner banner-warn">${escapeHtml(String(summary.trajectories_with_anomalies ?? 0))} trajectories with ${escapeHtml(String(summary.anomaly_count ?? 0))} anomaly tags (${escapeHtml(String(summary.error_count ?? 0))} error / ${escapeHtml(String(summary.warn_count ?? 0))} warn)</p>`
        : "";
    const items = safeArray(root.trajectories);
    if (items.length === 0) {
        return ["<h2>Anomalies</h2>", banner, '<p class="muted">No anomalies detected in stored trajectories.</p>'].join("\n");
    }
    const cards = items
        .map((raw) => {
            const item = safeObject(raw);
            if (!item) {
                return "";
            }
            const outcome = String(item.outcome || "?");
            const tier = String(item.quality_tier || "?");
            const agent = item.agent_label ? ` · ${item.agent_label}` : "";
            const tags = safeArray(item.anomalies)
                .map((tagRaw) => {
                    const tag = safeObject(tagRaw);
                    if (!tag) {
                        return "";
                    }
                    return `<li><span class="${pillClassForSeverity(tag.severity)}">${escapeHtml(String(tag.severity || "?"))}</span> <code>${escapeHtml(String(tag.kind || "?"))}</code> — ${escapeHtml(String(tag.message || ""))}</li>`;
                })
                .join("");
            return [
                '<article class="card">',
                `<div class="card-head"><code>${escapeHtml(String(item.trajectory_id || "?"))}</code> <span class="${pillClassForOutcome(outcome)}">${escapeHtml(outcome)}</span> <span class="pill">${escapeHtml(tier)}</span></div>`,
                `<p class="meta">${escapeHtml(String(item.summary || ""))}${escapeHtml(agent)}</p>`,
                tags ? `<ul class="tag-list">${tags}</ul>` : "",
                "</article>",
            ].join("");
        })
        .join("\n");
    return ["<h2>Anomalies</h2>", banner, `<div class="card-grid">${cards}</div>`].join("\n");
}

/**
 * @param {object | null | undefined} payload
 * @param {string} workspaceName
 * @param {string} nonce
 */
function renderTrajectoryDashboardHtml(payload, workspaceName, nonce) {
    const root = safeObject(payload);
    const extraStyles = [
        ".card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:12px 0}",
        ".card{border:1px solid var(--vscode-widget-border,#444);border-radius:8px;padding:12px;background:var(--vscode-editor-inactiveSelectionBackground, rgba(127,127,127,.08))}",
        ".card-head{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px}",
        ".tag-list{margin:8px 0 0;padding-left:18px}",
        ".pill-ok{background:var(--vscode-testing-iconPassed,#2ea043);color:#fff}",
        ".pill-bad{background:var(--vscode-inputValidation-errorBorder,#f14c4c);color:#fff}",
        ".pill-warn{background:var(--vscode-inputValidation-warningBorder,#cca700);color:#000}",
    ].join("");
    const body = [
        statusSection(safeObject(root?.status)),
        agentsSection(safeObject(root?.agents)),
        anomaliesSection(safeObject(root?.anomalies)),
    ].join("\n");
    return [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">',
        `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">`,
        `<style nonce="${nonce}">${SHARED_STYLES}${extraStyles}</style>`,
        "</head>",
        "<body>",
        '<header class="header">',
        "<h1>Trajectory Dashboard</h1>",
        `<p class="meta">Workspace: ${escapeHtml(workspaceName)} · mirrors <code>codeclone memory trajectory dashboard</code></p>`,
        "</header>",
        body,
        '<footer class="meta"><p>Read-only forensics over Engineering Memory trajectories. Rebuild with <code>codeclone memory trajectory rebuild</code> after new audit events.</p></footer>',
        "</body>",
        "</html>",
    ].join("\n");
}

/**
 * @param {unknown} value
 */
function humanizeLabel(value) {
    return String(value || "")
        .split("_")
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}

/**
 * @param {unknown} iso
 */
function formatUtcTimestamp(iso) {
    const text = String(iso || "").trim();
    if (!text) {
        return "";
    }
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) {
        return text;
    }
    return date.toISOString().replace("T", " · ").replace(/\.\d{3}Z$/, " UTC");
}

/**
 * @param {unknown} started
 * @param {unknown} finished
 */
function formatTimeRange(started, finished) {
    const startText = formatUtcTimestamp(started);
    const finishText = formatUtcTimestamp(finished);
    if (startText && finishText) {
        return `${startText} → ${finishText}`;
    }
    return startText || finishText || "unknown";
}

/**
 * @param {unknown} started
 * @param {unknown} finished
 */
function trajectoryDurationSeconds(started, finished) {
    const startMs = Date.parse(String(started || ""));
    const finishMs = Date.parse(String(finished || ""));
    if (Number.isNaN(startMs) || Number.isNaN(finishMs)) {
        return null;
    }
    return Math.max(0, Math.floor((finishMs - startMs) / 1000));
}

/**
 * @param {unknown} started
 * @param {unknown} finished
 */
function durationTableRow(started, finished) {
    const seconds = trajectoryDurationSeconds(started, finished);
    const range = formatTimeRange(started, finished);
    if (seconds === null) {
        return `<tr><th>Trajectory duration</th><td><span class="meta">(${escapeHtml(range)})</span></td></tr>`;
    }
    return [
        "<tr><th>Trajectory duration</th><td>",
        `<strong>${escapeHtml(formatDurationSeconds(seconds))}</strong> `,
        `<span class="meta">(${escapeHtml(range)})</span>`,
        "</td></tr>",
    ].join("");
}

/**
 * @param {unknown} score
 */
function qualityScoreClass(score) {
    const value = Number(score);
    if (!Number.isFinite(value)) {
        return "quality-mid";
    }
    if (value >= 90) {
        return "quality-high";
    }
    if (value >= 70) {
        return "quality-mid";
    }
    return "quality-low";
}

/**
 * @param {number} value
 * @param {number} max
 * @param {string} fillClass
 */
function microGauge(value, max, fillClass) {
    const numeric = Number(value);
    const ceiling = Number(max);
    if (!Number.isFinite(numeric) || !Number.isFinite(ceiling) || ceiling <= 0) {
        return "";
    }
    const pct = Math.max(0, Math.min(100, (numeric / ceiling) * 100));
    return [
        '<svg class="micro-gauge" viewBox="0 0 100 4" role="presentation" aria-hidden="true">',
        '<rect class="micro-gauge-track" x="0" y="0" width="100" height="4" rx="2"/>',
        `<rect class="micro-gauge-fill ${fillClass}" x="0" y="0" width="${pct.toFixed(1)}" height="4" rx="2"/>`,
        "</svg>",
    ].join("");
}

/**
 * @param {unknown} score
 */
function complexityScoreClass(score) {
    const value = Number(score);
    if (!Number.isFinite(value)) {
        return "complexity-mid";
    }
    if (value >= 70) {
        return "complexity-high";
    }
    if (value >= 35) {
        return "complexity-mid";
    }
    return "complexity-low";
}

/**
 * @param {unknown} contractRaw
 */
function complexityCalculationDetails(contractRaw) {
    const contract = safeObject(contractRaw);
    const calculation = safeObject(contract?.complexity_calculation);
    if (!calculation) {
        return "";
    }
    const lines = safeArray(calculation.lines);
    if (lines.length === 0) {
        return "";
    }
    const rows = lines
        .map((raw) => {
            const line = safeObject(raw);
            if (!line) {
                return "";
            }
            const rawValue = line.raw ?? 0;
            const unit = line.unit ? String(line.unit) : "";
            const contribution = line.contribution ?? 0;
            const cap = line.cap ?? "";
            const atCap = Number(contribution) >= Number(cap) && Number(cap) > 0;
            return [
                `<tr class="${atCap ? "calc-row-cap" : ""}">`,
                `<td class="calc-label">${escapeHtml(String(line.label || line.id || ""))}</td>`,
                `<td class="calc-raw">${escapeHtml(String(rawValue))}${unit ? ` ${escapeHtml(unit)}` : ""}</td>`,
                `<td class="calc-score">${escapeHtml(String(contribution))} / ${escapeHtml(String(cap))}</td>`,
                "</tr>",
            ].join("");
        })
        .filter(Boolean)
        .join("");
    const formula = calculation.formula
        ? `<p class="meta calc-formula">${escapeHtml(String(calculation.formula))}</p>`
        : "";
    const hint = calculation.hint
        ? `<p class="meta calc-hint">${escapeHtml(String(calculation.hint))}</p>`
        : "";
    const bandLabel = calculation.band_label ? String(calculation.band_label) : "";
    return [
        '<details class="calculation-details complexity-calculation">',
        "<summary>Show calculation</summary>",
        formula,
        hint,
        '<table class="calc-table"><tbody>',
        rows,
        '<tr class="calc-row-total">',
        "<td>Total</td>",
        `<td class="calc-raw">${bandLabel ? escapeHtml(bandLabel) : ""}</td>`,
        `<td class="calc-score">${escapeHtml(String(calculation.complexity_score ?? contract.complexity_score ?? ""))}</td>`,
        "</tr>",
        "</tbody></table>",
        "</details>",
    ].join("");
}

/**
 * @param {unknown} contractRaw
 */
function qualityCalculationDetails(contractRaw) {
    const contract = safeObject(contractRaw);
    const calculation = safeObject(contract?.calculation);
    if (!calculation) {
        return "";
    }
    const lines = safeArray(calculation.lines);
    if (lines.length === 0) {
        return "";
    }
    const rows = lines
        .map((raw) => {
            const line = safeObject(raw);
            if (!line) {
                return "";
            }
            const limits = line.limits_quality === true;
            const rowClass = limits ? "calc-row-limit" : "";
            const marker = line.pass === true ? "pass" : "fail";
            return [
                `<tr class="${rowClass}">`,
                `<td class="calc-label">${escapeHtml(String(line.label || line.id || ""))}</td>`,
                `<td class="calc-score ${marker}">${escapeHtml(String(line.score ?? ""))}</td>`,
                `<td class="calc-flag">${limits ? "← limits score" : ""}</td>`,
                "</tr>",
            ].join("");
        })
        .filter(Boolean)
        .join("");
    const formula = calculation.formula
        ? `<p class="meta calc-formula">${escapeHtml(String(calculation.formula))}</p>`
        : "";
    return [
        '<details class="calculation-details quality-calculation">',
        "<summary>Show calculation</summary>",
        formula,
        '<table class="calc-table"><tbody>',
        rows,
        '<tr class="calc-row-total">',
        "<td>Total</td>",
        `<td class="calc-score">${escapeHtml(String(calculation.quality_score ?? contract.quality_score ?? ""))}</td>`,
        "<td></td>",
        "</tr>",
        "</tbody></table>",
        "</details>",
    ].join("");
}

/**
 * @param {unknown} contractRaw
 */
function complexityFactorsList(contractRaw) {
    const contract = safeObject(contractRaw);
    const calculation = safeObject(contract?.complexity_calculation);
    const lines = safeArray(calculation?.lines);
    if (lines.length === 0) {
        return '<p class="meta">Complexity breakdown unavailable.</p>';
    }
    const items = lines
        .map((raw) => {
            const line = safeObject(raw);
            if (!line) {
                return "";
            }
            const contribution = line.contribution ?? 0;
            const cap = line.cap ?? 100;
            const fillClass = complexityScoreClass(
                cap > 0 ? (Number(contribution) / Number(cap)) * 100 : 0,
            );
            return [
                '<li class="factor-row">',
                `<span class="factor-label">${escapeHtml(String(line.label || line.id || ""))}</span>`,
                `<span class="factor-value">${escapeHtml(String(line.raw ?? 0))}</span>`,
                `<span class="factor-contrib">${escapeHtml(String(contribution))}</span>`,
                microGauge(contribution, cap, fillClass),
                "</li>",
            ].join("");
        })
        .filter(Boolean)
        .join("");
    const bandLabel = calculation?.band_label ? String(calculation.band_label) : "";
    const hint = calculation?.hint ? String(calculation.hint) : "";
    return [
        bandLabel ? `<p class="meta factor-band">${escapeHtml(bandLabel)} complexity</p>` : "",
        hint ? `<p class="meta factor-hint">${escapeHtml(hint)}</p>` : "",
        `<ul class="factor-list">${items}</ul>`,
    ].join("");
}

/**
 * @param {unknown} contractRaw
 */
function trajectoryAnalysisSection(contractRaw) {
    const contract = safeObject(contractRaw);
    const score = contract?.quality_score ?? null;
    if (score === null || score === undefined || score === "") {
        return "";
    }
    const components = safeArray(contract?.components);
    const checklist = components
        .map((raw) => {
            const item = safeObject(raw);
            if (!item) {
                return "";
            }
            const passed = item.pass === true;
            const mark = passed ? "✓" : "✗";
            const klass = passed ? "quality-check-pass" : "quality-check-fail";
            const detail = item.label ? String(item.label) : String(item.id || "");
            return [
                `<li class="${klass}">`,
                `<span class="quality-check-mark" aria-hidden="true">${mark}</span>`,
                `<span class="quality-check-label">${escapeHtml(detail)}</span>`,
                `<span class="quality-check-score">${escapeHtml(String(item.score ?? ""))}</span>`,
                "</li>",
            ].join("");
        })
        .filter(Boolean)
        .join("");
    return [
        '<section class="analysis-grid">',
        '<div class="analysis-panel analysis-panel-quality">',
        '<div class="section-heading">Contract gates</div>',
        checklist
            ? `<ul class="quality-checklist">${checklist}</ul>`
            : '<p class="meta">Contract breakdown unavailable.</p>',
        qualityCalculationDetails(contract),
        "</div>",
        '<div class="analysis-panel analysis-panel-complexity">',
        '<div class="section-heading">Complexity factors</div>',
        complexityFactorsList(contract),
        complexityCalculationDetails(contract),
        "</div>",
        "</section>",
    ].join("");
}

/**
 * @param {string} label
 * @param {string} valueHtml
 * @param {string} [gaugeHtml]
 * @param {string} [extraClass]
 * @param {string} [title]
 */
function passportMetricCell(label, valueHtml, gaugeHtml = "", extraClass = "", title = "") {
    const titleAttr = title ? ` title="${escapeHtml(title)}"` : "";
    return [
        `<div class="passport-cell ${extraClass}"${titleAttr}>`,
        `<div class="passport-cell-label">${escapeHtml(label)}</div>`,
        `<div class="passport-cell-value">${valueHtml}</div>`,
        gaugeHtml,
        "</div>",
    ].join("");
}

/**
 * @param {object | null | undefined} root
 */
function passportStrip(root) {
    if (!root) {
        return "";
    }
    const contract = safeObject(root.quality_contract);
    const quality = contract?.quality_score ?? root.quality_score;
    const complexity = contract?.complexity_score ?? root.complexity_score;
    const complexityCalc = safeObject(contract?.complexity_calculation);
    const bandLabel = complexityCalc?.band_label ? String(complexityCalc.band_label) : "";
    const durationSeconds =
        contract?.duration_seconds ??
        root.duration_seconds ??
        trajectoryDurationSeconds(root.started_at_utc, root.finished_at_utc);
    const durationText =
        durationSeconds !== null && durationSeconds !== undefined && durationSeconds !== ""
            ? formatDurationSeconds(Number(durationSeconds))
            : "—";
    const durationTitle = formatTimeRange(root.started_at_utc, root.finished_at_utc);
    const qualityValue =
        quality !== null && quality !== undefined && quality !== ""
            ? `<span class="${qualityScoreClass(quality)}">${escapeHtml(String(quality))}<span class="quality-score-denom">/100</span></span>`
            : "—";
    const complexityValue =
        complexity !== null && complexity !== undefined && complexity !== ""
            ? [
                  `<span class="${complexityScoreClass(complexity)}">${escapeHtml(String(complexity))}<span class="quality-score-denom">/100</span></span>`,
                  bandLabel ? `<span class="passport-band">${escapeHtml(bandLabel)}</span>` : "",
              ].join("")
            : "—";
    return [
        '<section class="passport-rail" aria-label="Trajectory metrics">',
        passportMetricCell(
            "Contract quality",
            qualityValue,
            "",
            "",
            "Deterministic change-contract adherence (not code quality).",
        ),
        passportMetricCell("Complexity", complexityValue),
        passportMetricCell(
            "Duration",
            escapeHtml(durationText),
            "",
            "",
            durationTitle,
        ),
        passportMetricCell("Events", escapeHtml(String(root.event_count ?? 0))),
        passportMetricCell("Steps", escapeHtml(String(root.step_count ?? 0))),
        passportMetricCell("Incidents", escapeHtml(String(root.incident_count ?? 0))),
        passportMetricCell("Evidence", escapeHtml(String(root.evidence_count ?? 0))),
        "</section>",
    ].join("");
}

/**
 * @param {unknown} score
 */
function qualityScoreSection(score) {
    if (score === null || score === undefined || score === "") {
        return "";
    }
    return [
        '<div class="quality-score-box">',
        '<div class="section-heading">Contract quality</div>',
        `<div class="quality-score-value ${qualityScoreClass(score)}">`,
        `${escapeHtml(String(score))}<span class="quality-score-denom">/100</span>`,
        "</div>",
        "</div>",
    ].join("");
}

/**
 * @param {unknown} stepsRaw
 */
function intentDescriptionFromSteps(stepsRaw) {
    for (const raw of safeArray(stepsRaw)) {
        const step = safeObject(raw);
        if (!step) {
            continue;
        }
        const eventType = String(step.event_type || "");
        if (eventType === "intent.declared" && step.summary) {
            return String(step.summary);
        }
    }
    return "";
}

/**
 * @param {unknown} summary
 */
function firstSummaryFromMachineSummary(summary) {
    const text = String(summary || "");
    const marker = "first_summary=";
    const index = text.indexOf(marker);
    if (index < 0) {
        return "";
    }
    return text.slice(index + marker.length).trim();
}

/**
 * @param {unknown} value
 * @param {"scope"|"verification"} kind
 */
function pillClassForTrailStatus(value, kind) {
    const status = String(value || "").toLowerCase();
    if (kind === "scope") {
        if (status === "clean") {
            return "pill pill-ok";
        }
        if (status === "violated") {
            return "pill pill-bad";
        }
        if (status === "expanded") {
            return "pill pill-warn";
        }
        return "pill pill-muted";
    }
    if (status === "accepted" || status === "accepted_with_external_changes") {
        return "pill pill-ok";
    }
    if (status === "unverified") {
        return "pill pill-warn";
    }
    if (status === "violated" || status === "blocked") {
        return "pill pill-bad";
    }
    return "pill pill-muted";
}

/**
 * @param {unknown} value
 * @param {unknown} kind
 */
function trailStatusLabel(value, kind) {
    const status = String(value || "?");
    if (kind === "scope") {
        return `Scope ${status}`;
    }
    return `Verification ${status.replace(/_/g, " ")}`;
}

/**
 * @param {unknown} value
 * @param {string} label
 * @param {string} [extraClass]
 */
function statCard(value, label, extraClass = "") {
    const klass = extraClass ? ` stat-card ${extraClass}` : " stat-card";
    return [
        `<div class="${klass.trim()}">`,
        `<div class="stat-value">${escapeHtml(String(value ?? 0))}</div>`,
        `<div class="stat-label">${escapeHtml(label)}</div>`,
        "</div>",
    ].join("");
}

/**
 * @param {object | null | undefined} patchSummary
 */
function patchTrailSection(patchSummary) {
    const root = safeObject(patchSummary);
    if (!root) {
        return "";
    }
    const counts = safeObject(root.counts) || {};
    const declared = counts.declared ?? 0;
    const changed = counts.changed ?? 0;
    const untouched = counts.untouched_in_declared ?? 0;
    const unexpected = counts.unexpected ?? 0;
    const forbidden = counts.forbidden_touched ?? 0;
    const statusRow = [
        root.scope_check_status
            ? `<span class="${pillClassForTrailStatus(root.scope_check_status, "scope")}">${escapeHtml(trailStatusLabel(root.scope_check_status, "scope"))}</span>`
            : "",
        root.verification_status
            ? `<span class="${pillClassForTrailStatus(root.verification_status, "verification")}">${escapeHtml(trailStatusLabel(root.verification_status, "verification"))}</span>`
            : "",
    ]
        .filter(Boolean)
        .join("");
    const countCells = [
        ["Declared", declared, ""],
        ["Changed", changed, ""],
        ["Untouched", untouched, untouched > 0 ? "patch-count-warn" : ""],
        ["Unexpected", unexpected, unexpected > 0 ? "patch-count-bad" : "patch-count-ok"],
    ];
    if (forbidden > 0) {
        countCells.push(["Forbidden", forbidden, "patch-count-bad"]);
    }
    const countRow = countCells
        .map(
            ([label, value, klass]) =>
                `<td class="patch-count ${klass}"><span class="patch-count-label">${escapeHtml(String(label))}</span><span class="patch-count-value">${escapeHtml(String(value))}</span></td>`,
        )
        .join("");
    return [
        '<section class="patch-trail-section">',
        '<div class="section-head">',
        '<h2 class="section-heading">Patch trail</h2>',
        statusRow ? `<div class="status-row">${statusRow}</div>` : "",
        "</div>",
        `<table class="patch-trail-table"><tr>${countRow}</tr></table>`,
        "</section>",
    ].join("\n");
}

/**
 * @param {object | null | undefined} root
 */
function trajectoryOverviewSection(root) {
    if (!root) {
        return "";
    }
    const intentId = root.intent_id || String(root.workflow_id || "").replace(/^intent:/, "");
    const description =
        intentDescriptionFromSteps(root.steps) ||
        firstSummaryFromMachineSummary(root.summary) ||
        "";
    const patchSummary = safeObject(root.patch_trail_summary);
    const metaRows = [
        intentId
            ? `<tr><th>Intent</th><td><code>${escapeHtml(String(intentId))}</code></td></tr>`
            : "",
        root.workflow_id
            ? `<tr><th>Workflow</th><td><code>${escapeHtml(String(root.workflow_id))}</code></td></tr>`
            : "",
        root.agent_label
            ? `<tr><th>Agent</th><td><code>${escapeHtml(String(root.agent_label))}</code></td></tr>`
            : "",
        root.primary_run_id
            ? `<tr><th>Primary run</th><td><code>${escapeHtml(String(root.primary_run_id))}</code></td></tr>`
            : "",
        root.first_run_id && root.first_run_id !== root.primary_run_id
            ? `<tr><th>First run</th><td><code>${escapeHtml(String(root.first_run_id))}</code></td></tr>`
            : "",
        root.last_run_id && root.last_run_id !== root.primary_run_id
            ? `<tr><th>Last run</th><td><code>${escapeHtml(String(root.last_run_id))}</code></td></tr>`
            : "",
    ]
        .filter(Boolean)
        .join("");
    const descriptionBlock = description
        ? [
              '<div class="intent-callout">',
              "<h2>Intent description</h2>",
              `<p>${escapeHtml(description)}</p>`,
              "</div>",
          ].join("")
        : "";
    return [
        passportStrip(root),
        patchTrailSection(patchSummary),
        trajectoryAnalysisSection(root.quality_contract) || qualityScoreSection(root.quality_score),
        '<table class="summary-table overview-table"><tbody>',
        metaRows,
        "</tbody></table>",
        descriptionBlock,
    ].join("\n");
}

/**
 * Compact QuickPick line from structured trajectory preview fields.
 *
 * @param {object | null | undefined} item
 */
function formatTrajectoryPickDescription(item) {
    const row = safeObject(item);
    if (!row) {
        return "";
    }
    let incidents = row.incident_count;
    if (incidents === null || incidents === undefined) {
        const match = String(row.summary || "").match(/incidents=(\d+)/);
        incidents = match ? match[1] : 0;
    }
    const parts = [`${row.event_count ?? 0} events`, `${incidents} incidents`];
    if (row.quality_score !== null && row.quality_score !== undefined) {
        parts.push(`${row.quality_score}/100 contract`);
    }
    if (row.agent_label) {
        parts.push(String(row.agent_label));
    }
    if (row.started_at_utc) {
        parts.push(formatUtcTimestamp(row.started_at_utc));
    }
    return parts.join(" · ");
}

/**
 * @param {object | null | undefined} step
 */
function timelineStepTitle(step) {
    const row = safeObject(step);
    if (!row) {
        return "?";
    }
    const label = String(row.step_label || row.event_type || "?");
    return label.replace(/\s\([^)]+\)\s*$/, "");
}

/**
 * @param {object | null | undefined} step
 * @returns {"ok"|"warn"|"bad"}
 */
function timelineStepTone(step) {
    const row = safeObject(step);
    if (!row) {
        return "ok";
    }
    const status = String(row.status || "").toLowerCase();
    const eventType = String(row.event_type || "").toLowerCase();
    const badStatuses = new Set([
        "violated",
        "blocked",
        "failed",
        "error",
        "not_reached",
        "rejected",
    ]);
    const warnStatuses = new Set([
        "unverified",
        "needs_attention",
        "partial",
        "abandoned",
        "accepted_with_external_changes",
        "warn",
        "incident",
        "queued",
        "expired",
    ]);
    const badEventHints = [
        "violated",
        "abuse",
        "conflict",
        "failed",
        "queue_blocked",
    ];
    const warnEventHints = ["expired", "recovered", "blocked"];
    if (
        badStatuses.has(status) ||
        badEventHints.some((hint) => eventType.includes(hint))
    ) {
        return "bad";
    }
    if (
        warnStatuses.has(status) ||
        warnEventHints.some((hint) => eventType.includes(hint))
    ) {
        return "warn";
    }
    return "ok";
}

/**
 * @param {object | null | undefined} step
 */
function timelineStepSummary(step) {
    const row = safeObject(step);
    if (!row || !row.summary) {
        return "";
    }
    const summary = String(row.summary).trim();
    const status = String(row.status || "").trim().toLowerCase();
    if (status && summary.toLowerCase() === `review receipt: ${status}`) {
        return "";
    }
    return summary;
}

/**
 * @param {object | null | undefined} step
 */
function timelineStepStatusLabel(step) {
    const row = safeObject(step);
    if (!row || !row.status) {
        return "";
    }
    return String(row.status).replace(/_/g, " ");
}

/**
 * @param {object | null | undefined} trajectory
 * @param {string} workspaceName
 * @param {string} nonce
 */
function renderTrajectoryDetailHtml(trajectory, workspaceName, nonce) {
    const root = safeObject(trajectory);
    if (!root) {
        return "<!DOCTYPE html><html><body><p>No trajectory detail.</p></body></html>";
    }
    const steps = safeArray(root.steps)
        .map((raw, index) => {
            const step = safeObject(raw);
            if (!step) {
                return "";
            }
            const tone = timelineStepTone(step);
            const title = timelineStepTitle(step);
            const statusLabel = timelineStepStatusLabel(step);
            const summary = timelineStepSummary(step);
            return [
                '<div class="timeline-row">',
                `<div class="timeline-index timeline-index-${tone}" title="${escapeHtml(statusLabel || tone)}">${index + 1}</div>`,
                '<div class="timeline-body">',
                `<div><strong>${escapeHtml(title)}</strong> <span class="meta">#${escapeHtml(String(step.audit_sequence ?? "?"))}</span></div>`,
                summary ? `<div class="meta">${escapeHtml(summary)}</div>` : "",
                step.created_at_utc
                    ? `<div class="meta">${escapeHtml(formatUtcTimestamp(step.created_at_utc))}</div>`
                    : "",
                "</div>",
                "</div>",
            ].join("");
        })
        .join("");
    const labels = safeArray(root.labels)
        .map((label) => `<span class="pill pill-muted">${escapeHtml(humanizeLabel(label))}</span>`)
        .join(" ");
    const extraStyles = [
        ".timeline{display:flex;flex-direction:column;gap:10px;margin-top:16px}",
        ".timeline-row{display:grid;grid-template-columns:28px 1fr;gap:10px;align-items:start}",
        ".timeline-index{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.85em;font-weight:600;flex-shrink:0}",
        ".timeline-index-ok{background:var(--vscode-testing-iconPassed,#2ea043);color:#fff}",
        ".timeline-index-warn{background:var(--vscode-inputValidation-warningBorder,#cca700);color:#000}",
        ".timeline-index-bad{background:var(--vscode-inputValidation-errorBorder,#f14c4c);color:#fff}",
        ".label-row{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px}",
        ".stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:10px;margin:14px 0 4px}",
        ".stat-card{border:1px solid var(--vscode-widget-border,#444);border-radius:8px;padding:12px 10px;text-align:center;background:var(--vscode-editor-inactiveSelectionBackground, rgba(127,127,127,.08))}",
        ".stat-value{font-size:1.35em;font-weight:700;line-height:1.1;color:var(--vscode-foreground)}",
        ".stat-label{font-size:.72em;color:var(--vscode-descriptionForeground);text-transform:uppercase;letter-spacing:.05em;margin-top:6px}",
        ".passport-rail{display:grid;grid-template-columns:minmax(88px,1.2fr) minmax(88px,1.2fr) repeat(5,minmax(52px,1fr));gap:0;margin:10px 0 12px;border:1px solid var(--vscode-widget-border,#444);border-radius:6px;overflow:hidden;background:var(--vscode-editor-inactiveSelectionBackground, rgba(127,127,127,.04))}",
        ".passport-cell{padding:7px 8px;border-right:1px solid var(--vscode-widget-border,#444);min-width:0}",
        ".passport-cell:last-child{border-right:none}",
        ".passport-cell-label{font-size:.62em;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--vscode-descriptionForeground);margin-bottom:3px;line-height:1.1}",
        ".passport-cell-value{font-size:.92em;font-weight:600;font-variant-numeric:tabular-nums;line-height:1.2}",
        ".passport-band{display:block;margin-top:2px;font-size:.72em;font-weight:500;color:var(--vscode-descriptionForeground);line-height:1.1}",
        ".micro-gauge{display:block;width:100%;height:3px;flex-shrink:0}",
        ".micro-gauge-track{fill:var(--vscode-widget-border,#444);opacity:.45}",
        ".micro-gauge-fill.quality-high{fill:var(--vscode-testing-iconPassed,#2ea043)}",
        ".micro-gauge-fill.quality-mid{fill:var(--vscode-inputValidation-warningBorder,#cca700)}",
        ".micro-gauge-fill.quality-low{fill:var(--vscode-inputValidation-errorBorder,#f14c4c)}",
        ".micro-gauge-fill.complexity-high{fill:var(--vscode-textLink-foreground,#3794ff)}",
        ".micro-gauge-fill.complexity-mid{fill:var(--vscode-foreground);opacity:.55}",
        ".micro-gauge-fill.complexity-low{fill:var(--vscode-descriptionForeground);opacity:.45}",
        ".analysis-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:12px 0 4px}",
        ".analysis-panel{padding:10px 12px;border:1px solid var(--vscode-widget-border,#444);border-radius:8px;background:var(--vscode-editor-inactiveSelectionBackground, rgba(127,127,127,.04))}",
        ".factor-list{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-direction:column;gap:8px}",
        ".factor-row{display:grid;grid-template-columns:1fr auto auto;grid-template-rows:auto auto;gap:2px 10px;align-items:center;font-size:.88em}",
        ".factor-label{grid-column:1;color:var(--vscode-foreground)}",
        ".factor-value{grid-column:2;font-variant-numeric:tabular-nums;color:var(--vscode-descriptionForeground)}",
        ".factor-contrib{grid-column:3;font-weight:600;font-variant-numeric:tabular-nums}",
        ".factor-row .micro-gauge{grid-column:1/-1;margin-top:2px}",
        ".factor-band,.factor-hint{margin:6px 0 0;font-size:.85em}",
        ".patch-trail-table{width:100%;border-collapse:collapse;margin-top:0}",
        ".patch-trail-table td{padding:8px 10px;border:1px solid var(--vscode-widget-border,#444);border-radius:6px;background:var(--vscode-editor-inactiveSelectionBackground, rgba(127,127,127,.04))}",
        ".patch-trail-table tr{display:grid;grid-template-columns:repeat(auto-fit,minmax(72px,1fr));gap:8px}",
        ".patch-count{display:flex;flex-direction:column;gap:4px;text-align:center}",
        ".patch-count-label{font-size:.68em;text-transform:uppercase;letter-spacing:.05em;color:var(--vscode-descriptionForeground)}",
        ".patch-count-value{font-size:1.05em;font-weight:700;font-variant-numeric:tabular-nums}",
        ".patch-count-warn .patch-count-value{color:var(--vscode-inputValidation-warningBorder,#cca700)}",
        ".patch-count-bad .patch-count-value{color:var(--vscode-inputValidation-errorBorder,#f14c4c)}",
        ".patch-count-ok .patch-count-value{color:var(--vscode-testing-iconPassed,#2ea043)}",
        ".overview-table{margin-top:4px}",
        ".intent-callout{border-left:3px solid var(--vscode-textLink-foreground,#3794ff);padding:10px 14px;margin:14px 0;background:var(--vscode-editor-inactiveSelectionBackground, rgba(127,127,127,.08));border-radius:0 8px 8px 0}",
        ".intent-callout h2,.section-heading,.timeline-heading{font-size:.78em;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--vscode-descriptionForeground);margin:0 0 8px}",
        ".intent-callout p{margin:0;line-height:1.45}",
        ".patch-trail-section{margin:12px 0 4px;padding-top:12px;border-top:1px solid var(--vscode-widget-border,#444)}",
        ".section-head{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;justify-content:space-between;margin-bottom:8px}",
        ".section-head .section-heading{margin:0}",
        ".section-head .status-row{margin:0}",
        ".pill-muted{background:var(--vscode-badge-background);color:var(--vscode-badge-foreground)}",
        ".pill-ok{background:var(--vscode-testing-iconPassed,#2ea043);color:#fff}",
        ".pill-bad{background:var(--vscode-inputValidation-errorBorder,#f14c4c);color:#fff}",
        ".pill-warn{background:var(--vscode-inputValidation-warningBorder,#cca700);color:#000}",
        ".status-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}",
        ".quality-score-box{padding:12px 14px;border:1px solid var(--vscode-widget-border,#444);border-radius:8px;background:var(--vscode-editor-inactiveSelectionBackground, rgba(127,127,127,.08))}",
        ".quality-score-value{font-size:1.35em;font-weight:700;line-height:1.1}",
        ".quality-score-denom{font-size:.55em;font-weight:600;color:var(--vscode-descriptionForeground);margin-left:2px}",
        ".quality-checklist{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-direction:column;gap:5px}",
        ".quality-checklist li{display:grid;grid-template-columns:1.2em 1fr auto;gap:8px;align-items:baseline;font-size:.88em}",
        ".quality-check-pass .quality-check-mark{color:var(--vscode-testing-iconPassed,#2ea043)}",
        ".quality-check-fail .quality-check-mark{color:var(--vscode-inputValidation-errorBorder,#f14c4c)}",
        ".quality-check-score{font-variant-numeric:tabular-nums;color:var(--vscode-descriptionForeground)}",
        ".calculation-details{margin-top:10px}",
        ".calculation-details summary{cursor:pointer;font-size:.85em;color:var(--vscode-textLink-foreground,#3794ff)}",
        ".calc-formula,.calc-hint{margin:8px 0 0}",
        ".calc-table{width:100%;border-collapse:collapse;margin-top:8px;font-size:.85em}",
        ".calc-table td{padding:4px 6px;border-top:1px solid var(--vscode-widget-border,#444)}",
        ".calc-label{color:var(--vscode-foreground)}",
        ".calc-raw{text-align:right;font-variant-numeric:tabular-nums;color:var(--vscode-descriptionForeground)}",
        ".calc-score{text-align:right;font-variant-numeric:tabular-nums;width:4.5em}",
        ".calc-score.pass{color:var(--vscode-testing-iconPassed,#2ea043)}",
        ".calc-score.fail{color:var(--vscode-inputValidation-errorBorder,#f14c4c)}",
        ".calc-flag{font-size:.85em;color:var(--vscode-descriptionForeground)}",
        ".calc-row-limit td{background:var(--vscode-list-hoverBackground, rgba(127,127,127,.12))}",
        ".calc-row-cap td{background:var(--vscode-list-hoverBackground, rgba(127,127,127,.08))}",
        ".calc-row-total td{font-weight:600;border-top:2px solid var(--vscode-widget-border,#444)}",
        ".quality-high{color:var(--vscode-testing-iconPassed,#2ea043)}",
        ".quality-mid{color:var(--vscode-inputValidation-warningBorder,#cca700)}",
        ".quality-low{color:var(--vscode-inputValidation-errorBorder,#f14c4c)}",
        ".complexity-high{color:var(--vscode-textLink-foreground,#3794ff)}",
        ".complexity-mid{color:var(--vscode-foreground)}",
        ".complexity-low{color:var(--vscode-descriptionForeground)}",
    ].join("");
    return [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">`,
        `<style nonce="${nonce}">${SHARED_STYLES}${extraStyles}</style>`,
        "</head>",
        "<body>",
        '<header class="header">',
        `<h1>Trajectory <code class="trajectory-id">${escapeHtml(String(root.trajectory_id || ""))}</code></h1>`,
        `<p class="meta">Workspace: ${escapeHtml(workspaceName)}</p>`,
        '<div class="status-row">',
        `<span class="${pillClassForOutcome(root.outcome)}">${escapeHtml(String(root.outcome || "?"))}</span>`,
        `<span class="${pillClassForOutcome(root.quality_tier === "verified" ? "accepted" : root.quality_tier)}">${escapeHtml(String(root.quality_tier || "?"))}</span>`,
        "</div>",
        labels ? `<div class="label-row">${labels}</div>` : "",
        trajectoryOverviewSection(root),
        "</header>",
        '<section class="timeline">',
        '<h2 class="timeline-heading">Event timeline</h2>',
        steps || '<p class="muted">No steps returned.</p>',
        "</section>",
        "</body>",
        "</html>",
    ].join("\n");
}

/**
 * @param {object | null | undefined} payload
 */
function renderTrajectoryDashboardMarkdown(payload) {
    const root = safeObject(payload);
    const lines = ["# Trajectory dashboard", ""];
    const status = safeObject(root?.status);
    if (status) {
        lines.push(`- Stored trajectories: ${status.trajectory_count ?? 0}`);
    }
    const agents = safeObject(root?.agents);
    if (agents) {
        lines.push("", "## Agents");
        for (const raw of safeArray(agents.agents).slice(0, 20)) {
            const row = safeObject(raw);
            if (!row) {
                continue;
            }
            lines.push(
                `- \`${row.agent_label}\`: ${row.trajectory_count ?? 0} trajectories, ${row.anomaly_count ?? 0} anomaly tags`
            );
        }
    }
    const anomalies = safeObject(root?.anomalies);
    if (anomalies) {
        lines.push("", "## Anomalies");
        for (const raw of safeArray(anomalies.trajectories).slice(0, 10)) {
            const item = safeObject(raw);
            if (!item) {
                continue;
            }
            lines.push(`- \`${item.trajectory_id}\` ${item.outcome}/${item.quality_tier}`);
        }
    }
    return lines.join("\n");
}

module.exports = {
    renderTrajectoryDashboardHtml,
    renderTrajectoryDetailHtml,
    renderTrajectoryDashboardMarkdown,
    formatTrajectoryPickDescription,
};
