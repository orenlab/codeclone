"use strict";

const path = require("node:path");
/** @type {any} */
const vscode = require("vscode");

const {
    HOTSPOT_FOCUS_MODES,
} = require("./constants");
const {resolveWorkspacePath} = require("./support");

/**
 * @typedef {Object.<string, any>} LooseObject
 */

/**
 * @typedef {{
 *   path: string,
 *   line: number | null,
 *   end_line: number | null,
 *   symbol: string | null
 * }} FindingLocation
 */

/**
 * @typedef {FindingLocation & { absolutePath: string }} NormalizedFindingLocation
 */

function number(value) {
    if (typeof value !== "number" || Number.isNaN(value)) {
        return "0";
    }
    return value.toLocaleString("en-US");
}

function decimal(value, digits = 2) {
    if (typeof value !== "number" || Number.isNaN(value)) {
        return "0.00";
    }
    return value.toFixed(digits);
}

function compactDecimal(value) {
    if (typeof value !== "number" || Number.isNaN(value)) {
        return "0";
    }
    return value.toFixed(2).replace(/\.?0+$/, "");
}

function capitalize(value) {
    if (!value) {
        return "";
    }
    return value.charAt(0).toUpperCase() + value.slice(1);
}

function humanizeIdentifier(value) {
    const text = String(value || "").trim().replace(/_/g, " ");
    return text ? capitalize(text) : "";
}

function formatBooleanWord(value) {
    return value ? "yes" : "no";
}

function formatBaselineState(payload) {
    const entry = safeObject(payload);
    const status = String(entry.status || "unknown");
    const parts = [status, entry.trusted ? "trusted" : "untrusted"];
    if (entry.compared_without_valid_baseline) {
        parts.push("comparing without valid baseline");
    }
    return parts.join(" · ");
}

function formatBaselineTags(payload) {
    const entry = safeObject(payload);
    const baselinePythonTag = String(entry.baseline_python_tag || "").trim();
    const runtimePythonTag = String(entry.runtime_python_tag || "").trim();
    const parts = [];
    if (baselinePythonTag) {
        parts.push(`baseline ${baselinePythonTag}`);
    }
    if (runtimePythonTag) {
        parts.push(`runtime ${runtimePythonTag}`);
    }
    return parts.length > 0 ? parts.join(" · ") : "unknown";
}

function formatCacheSummary(payload) {
    const entry = safeObject(payload);
    const usage = entry.used ? "used" : "fresh";
    const freshness = entry.freshness ? String(entry.freshness) : "unknown";
    return `${usage} · ${freshness}`;
}

function coverageJoinPayload(metricsSummary) {
    return safeObject(safeObject(metricsSummary).coverage_join);
}

function isCoverageJoinReviewItem(item) {
    const entry = safeObject(item);
    return Boolean(
        entry.coverage_review_item ||
        entry.coverage_hotspot ||
        entry.scope_gap_hotspot
    );
}

function coverageJoinReviewItemCount(summary, items) {
    const entry = safeObject(summary);
    if (
        Object.prototype.hasOwnProperty.call(entry, "coverage_hotspots") ||
        Object.prototype.hasOwnProperty.call(entry, "scope_gap_hotspots")
    ) {
        return (
            (finiteInteger(entry.coverage_hotspots) ?? 0) +
            (finiteInteger(entry.scope_gap_hotspots) ?? 0)
        );
    }
    return safeArray(items).filter(isCoverageJoinReviewItem).length;
}

function metricSummaryCount(metricsSummary, family, key) {
    return finiteInteger(safeObject(safeObject(metricsSummary)[family])[key]) ?? 0;
}

function securitySurfacesPayload(metricsSummary) {
    return safeObject(safeObject(metricsSummary).security_surfaces);
}

function countedNoun(value, singular, plural = `${singular}s`) {
    const normalized =
        typeof value === "number" && !Number.isNaN(value) ? value : 0;
    return `${number(normalized)} ${normalized === 1 ? singular : plural}`;
}

function formatCoverageJoinStatus(payload) {
    const status = String(safeObject(payload).status || "").trim().toLowerCase();
    switch (status) {
        case "ok":
            return "joined";
        case "missing":
            return "unavailable";
        case "invalid":
            return "invalid";
        default:
            return status ? status.replace(/_/g, " ") : "unavailable";
    }
}

function formatCoverageJoinPercent(payload) {
    const permille = safeObject(payload).overall_permille;
    if (typeof permille !== "number" || Number.isNaN(permille)) {
        return "n/a";
    }
    return `${compactDecimal(permille / 10)}%`;
}

function formatCoverageJoinMeasuredUnits(payload) {
    const entry = safeObject(payload);
    const measuredUnits =
        typeof entry.measured_units === "number" && !Number.isNaN(entry.measured_units)
            ? entry.measured_units
            : null;
    const totalUnits =
        typeof entry.units === "number" && !Number.isNaN(entry.units)
            ? entry.units
            : null;
    if (measuredUnits === null && totalUnits === null) {
        return "n/a";
    }
    if (measuredUnits !== null && totalUnits !== null) {
        return `${number(measuredUnits)} / ${number(totalUnits)}`;
    }
    return number(measuredUnits !== null ? measuredUnits : totalUnits);
}

function formatCoverageJoinSummary(payload) {
    const entry = safeObject(payload);
    if (Object.keys(entry).length === 0) {
        return "";
    }
    if (String(entry.status || "").trim().toLowerCase() === "ok") {
        const parts = [
            `${formatCoverageJoinPercent(entry)} overall`,
            countedNoun(entry.coverage_hotspots, "hotspot"),
        ];
        const scopeGaps =
            typeof entry.scope_gap_hotspots === "number" &&
            !Number.isNaN(entry.scope_gap_hotspots)
                ? entry.scope_gap_hotspots
                : 0;
        if (scopeGaps > 0) {
            parts.push(countedNoun(scopeGaps, "scope gap"));
        }
        return parts.join(" · ");
    }
    const parts = [formatCoverageJoinStatus(entry)];
    const source = String(entry.source || "").trim();
    if (source) {
        parts.push(path.basename(source));
    }
    return parts.join(" · ");
}

function formatCoverageJoinLocation(item) {
    return formatSecuritySurfaceLocation(item);
}

function formatCoverageJoinReviewSignal(item) {
    const entry = safeObject(item);
    if (entry.scope_gap_hotspot) {
        return "scope gap";
    }
    if (entry.coverage_hotspot) {
        return "low coverage";
    }
    return String(entry.coverage_status || "measured").replace(/_/g, " ");
}

function formatRunScope(value) {
    return value === "changed" ? "changed files" : "workspace";
}

function formatSourceKindSummary(value) {
    const entries = Object.entries(safeObject(value))
        .filter(([, count]) => typeof count === "number" && count > 0)
        .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey));
    if (entries.length === 0) {
        return "none";
    }
    return entries
        .map(([key, count]) => `${capitalize(key)} ${count}`)
        .join(" · ");
}

function sameLaunchSpec(left, right) {
    if (!left || !right) {
        return false;
    }
    const leftArgs = Array.isArray(left.args) ? left.args : [];
    const rightArgs = Array.isArray(right.args) ? right.args : [];
    return (
        left.command === right.command &&
        left.cwd === right.cwd &&
        JSON.stringify(leftArgs) === JSON.stringify(rightArgs)
    );
}

function normalizeRelativePath(value) {
    return String(value || "").replace(/\\/g, "/");
}

function workspaceRelativePath(folder, fsPath) {
    return normalizeRelativePath(path.relative(folder.uri.fsPath, fsPath));
}

function formatSeverity(value) {
    return capitalize(String(value || "info"));
}

function formatNovelty(value) {
    const novelty = String(value || "").trim();
    if (!novelty) {
        return "";
    }
    return capitalize(novelty);
}

function formatKind(value) {
    const kind = String(value || "");
    switch (kind) {
        case "function_clone":
            return "Function clone";
        case "block_clone":
            return "Block clone";
        case "segment_clone":
            return "Segment clone";
        case "class_hotspot":
            return "Class hotspot";
        case "module_hotspot":
            return "Module hotspot";
        case "duplicated_branches":
            return "Duplicated branches";
        default:
            return capitalize(kind.replace(/_/g, " "));
    }
}

function focusModeSpec(modeId) {
    return (
        HOTSPOT_FOCUS_MODES.find((entry) => entry.id === modeId) ||
        HOTSPOT_FOCUS_MODES[0]
    );
}

function isSpecificFocusMode(modeId) {
    return modeId !== "recommended" && modeId !== "all";
}

function reviewTargetKey(target) {
    if (!target || typeof target !== "object") {
        return "";
    }
    if (target.nodeType === "overloadedModule" && safeObject(target.item).path) {
        return `overloaded:${String(target.item.path)}`;
    }
    if (target.nodeType === "securitySurface") {
        const item = safeObject(target.item);
        const pathValue = String(item.path || "").trim();
        const qualnameValue = String(item.qualname || "").trim();
        const capabilityValue = String(item.capability || "").trim();
        const lineValue =
            typeof item.start_line === "number" && !Number.isNaN(item.start_line)
                ? item.start_line
                : 0;
        if (pathValue) {
            return `security:${pathValue}:${lineValue}:${qualnameValue}:${capabilityValue}`;
        }
    }
    if (target.nodeType === "coverageJoin") {
        const item = safeObject(target.item);
        const pathValue = String(item.path || "").trim();
        const qualnameValue = String(item.qualname || "").trim();
        const lineValue =
            typeof item.start_line === "number" && !Number.isNaN(item.start_line)
                ? item.start_line
                : 0;
        if (pathValue) {
            return `coverage:${pathValue}:${lineValue}:${qualnameValue}`;
        }
    }
    if (target.findingId) {
        return `finding:${String(target.findingId)}`;
    }
    return "";
}

function findingIcon(severity) {
    switch (String(severity || "").toLowerCase()) {
        case "critical":
            return new vscode.ThemeIcon(
                "error",
                new vscode.ThemeColor("problemsErrorIcon.foreground")
            );
        case "warning":
            return new vscode.ThemeIcon(
                "warning",
                new vscode.ThemeColor("problemsWarningIcon.foreground")
            );
        default:
            return new vscode.ThemeIcon(
                "info",
                new vscode.ThemeColor("problemsInfoIcon.foreground")
            );
    }
}

/**
 * @param {unknown} value
 * @returns {any[]}
 */
function safeArray(value) {
    return Array.isArray(value) ? value : [];
}

/**
 * @param {unknown} value
 * @returns {LooseObject}
 */
function safeObject(value) {
    return value && typeof value === "object" ? value : {};
}

function emptyReviewArtifacts() {
    return {
        newRegressions: [],
        productionHotspots: [],
        changedFiles: [],
        coverageJoin: [],
        overloadedModules: [],
        securitySurfaces: [],
    };
}

function formatSecuritySurfaceLocation(item) {
    const entry = safeObject(item);
    const pathValue = String(entry.path || "").trim();
    const startLine =
        typeof entry.start_line === "number" && !Number.isNaN(entry.start_line)
            ? entry.start_line
            : null;
    const endLine =
        typeof entry.end_line === "number" && !Number.isNaN(entry.end_line)
            ? entry.end_line
            : null;
    if (!pathValue) {
        return "(unknown)";
    }
    if (startLine === null || startLine <= 0) {
        return pathValue;
    }
    if (endLine !== null && endLine > startLine) {
        return `${pathValue}:${startLine}-${endLine}`;
    }
    return `${pathValue}:${startLine}`;
}

function formatSecuritySurfaceReviewSignal(item) {
    const entry = safeObject(item);
    const scopeText = humanizeIdentifier(entry.location_scope || "unknown");
    if (entry.scope_gap_hotspot) {
        return `${scopeText} · scope gap`;
    }
    if (entry.coverage_hotspot) {
        return `${scopeText} · low coverage`;
    }
    if (entry.coverage_overlap) {
        return `${scopeText} · coverage overlap`;
    }
    if (String(entry.location_scope || "").trim() === "module") {
        return `${scopeText} · capability present`;
    }
    return `${scopeText} · exact evidence`;
}

function finiteInteger(value) {
    if (typeof value === "number" && Number.isFinite(value)) {
        return Math.max(0, Math.trunc(value));
    }
    const parsed = Number.parseInt(String(value || ""), 10);
    return Number.isFinite(parsed) ? Math.max(0, parsed) : null;
}

function formatOverloadedModuleStatus(item) {
    const entry = safeObject(item);
    const rawStatus = String(entry.candidate_status || "").trim().toLowerCase();
    switch (rawStatus) {
        case "candidate":
            return "candidate";
        case "ranked_only":
            return "ranked-only";
        case "non_candidate":
            return "non-candidate";
        default:
            return "ranked";
    }
}

function isOverloadedModuleCandidate(item) {
    return formatOverloadedModuleStatus(item) === "candidate";
}

function overloadedModuleCandidateCount(summary, items) {
    const candidateCount = finiteInteger(safeObject(summary).candidates);
    if (candidateCount !== null) {
        return candidateCount;
    }
    return safeArray(items).filter(isOverloadedModuleCandidate).length;
}

function qualityReviewItemCount(metricsSummary, artifacts = {}) {
    const summary = safeObject(metricsSummary);
    const artifactItems = safeObject(artifacts);
    const securitySurfaces = securitySurfacesPayload(summary);
    const securitySurfaceCount =
        finiteInteger(securitySurfaces.items) ??
        safeArray(artifactItems.securitySurfaces).length;
    return (
        metricSummaryCount(summary, "complexity", "high_risk") +
        metricSummaryCount(summary, "coupling", "high_risk") +
        metricSummaryCount(summary, "cohesion", "low_cohesion") +
        overloadedModuleCandidateCount(
            safeObject(summary.overloaded_modules),
            safeArray(artifactItems.overloadedModules)
        ) +
        coverageJoinReviewItemCount(
            coverageJoinPayload(summary),
            safeArray(artifactItems.coverageJoin)
        ) +
        securitySurfaceCount
    );
}

function reportReviewItemCount(latestSummary, metricsSummary, triage, artifacts = {}) {
    const summary = safeObject(latestSummary);
    const metrics = safeObject(metricsSummary);
    const findings = safeObject(summary.findings);
    const byFamily = safeObject(findings.by_family);
    const deadCode = safeObject(metrics.dead_code);
    const dependencies = safeObject(metrics.dependencies);
    const suggestions = safeObject(safeObject(triage).suggestions);
    return (
        (finiteInteger(byFamily.clones) ?? 0) +
        qualityReviewItemCount(metrics, artifacts) +
        (finiteInteger(dependencies.cycles) ?? 0) +
        (finiteInteger(deadCode.high_confidence) ?? 0) +
        (finiteInteger(suggestions.total) ?? 0) +
        (finiteInteger(byFamily.structural) ?? 0)
    );
}

function formatOverloadedModulesSummary(summary, items) {
    const rows = safeArray(items);
    const payload = safeObject(summary);
    const candidates = overloadedModuleCandidateCount(payload, rows);
    const visible = rows.length;
    if (visible > 0 && visible !== candidates) {
        return `${number(candidates)} candidates · top ${number(visible)} ranked`;
    }
    return `${number(candidates)} candidates`;
}

/**
 * @param {unknown} value
 * @returns {FindingLocation[]}
 */
function normalizeLocations(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    const locations = value
        .map((entry) => {
            if (typeof entry === "string") {
                const match = entry.match(/^(.+):(\d+)$/);
                return {
                    path: match ? match[1] : entry,
                    line: match ? Number(match[2]) : null,
                    end_line: null,
                    symbol: null,
                };
            }
            if (entry && typeof entry === "object") {
                return {
                    path: entry.path ? String(entry.path) : "",
                    line: typeof entry.line === "number" ? entry.line : null,
                    end_line: typeof entry.end_line === "number" ? entry.end_line : null,
                    symbol: entry.symbol ? String(entry.symbol) : null,
                };
            }
            return null;
        })
        .filter(Boolean);
    return /** @type {FindingLocation[]} */ (locations);
}

/**
 * @param {any} folder
 * @param {unknown} value
 * @returns {NormalizedFindingLocation[]}
 */
function normalizeFindingLocations(folder, value) {
    const locations = normalizeLocations(value)
        .filter((location) => location.path)
        .map((location) => {
            const relativePath = normalizeRelativePath(location.path);
            const absolutePath = resolveWorkspacePath(folder.uri.fsPath, relativePath);
            if (!absolutePath) {
                return null;
            }
            return {
                ...location,
                path: relativePath,
                absolutePath,
            };
        })
        .filter(Boolean);
    return /** @type {NormalizedFindingLocation[]} */ (locations);
}

/**
 * @param {any} folder
 * @param {unknown} value
 * @returns {NormalizedFindingLocation | null}
 */
function firstNormalizedLocation(folder, value) {
    const locations = normalizeFindingLocations(folder, value);
    return locations.length > 0 ? locations[0] : null;
}

function treeAccessibilityInformation(node) {
    const label = String(node?.label || "").trim();
    const description = String(node?.description || "").trim();
    if (!label && !description) {
        return undefined;
    }
    const spoken = description ? `${label}, ${description}` : label;
    return {label: spoken};
}

module.exports = {
    capitalize,
    compactDecimal,
    decimal,
    emptyReviewArtifacts,
    findingIcon,
    firstNormalizedLocation,
    focusModeSpec,
    formatBaselineTags,
    formatBaselineState,
    formatBooleanWord,
    formatCacheSummary,
    coverageJoinPayload,
    coverageJoinReviewItemCount,
    formatCoverageJoinMeasuredUnits,
    formatCoverageJoinPercent,
    formatCoverageJoinLocation,
    formatCoverageJoinReviewSignal,
    formatCoverageJoinStatus,
    formatCoverageJoinSummary,
    formatOverloadedModuleStatus,
    formatOverloadedModulesSummary,
    formatSecuritySurfaceLocation,
    formatSecuritySurfaceReviewSignal,
    formatKind,
    formatNovelty,
    formatRunScope,
    formatSeverity,
    formatSourceKindSummary,
    humanizeIdentifier,
    isCoverageJoinReviewItem,
    isOverloadedModuleCandidate,
    isSpecificFocusMode,
    normalizeFindingLocations,
    normalizeLocations,
    normalizeRelativePath,
    number,
    overloadedModuleCandidateCount,
    qualityReviewItemCount,
    reportReviewItemCount,
    reviewTargetKey,
    safeArray,
    safeObject,
    securitySurfacesPayload,
    sameLaunchSpec,
    treeAccessibilityInformation,
    workspaceRelativePath,
};
