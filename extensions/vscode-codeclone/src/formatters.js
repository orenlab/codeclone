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
        overloadedModules: [],
    };
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
    formatKind,
    formatNovelty,
    formatRunScope,
    formatSeverity,
    formatSourceKindSummary,
    isSpecificFocusMode,
    normalizeFindingLocations,
    normalizeLocations,
    normalizeRelativePath,
    number,
    reviewTargetKey,
    safeArray,
    safeObject,
    sameLaunchSpec,
    treeAccessibilityInformation,
    workspaceRelativePath,
};
