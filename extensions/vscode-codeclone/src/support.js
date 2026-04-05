"use strict";

const path = require("node:path");

const STALE_REASON_EDITOR = "unsaved editor changes";
const STALE_REASON_WORKSPACE = "workspace changed after this run";
const ANALYSIS_PROFILE_DEFAULTS = "defaults";
const ANALYSIS_PROFILE_DEEPER_REVIEW = "deeperReview";
const ANALYSIS_PROFILE_CUSTOM = "custom";
const MINIMUM_SUPPORTED_CODECLONE_VERSION = "2.0.0b4";
const PREVIEW_INSTALL_COMMAND =
    'uv tool install "codeclone[mcp]>=2.0.0b4"';
const ANALYSIS_PROFILE_IDS = new Set([
    ANALYSIS_PROFILE_DEFAULTS,
    ANALYSIS_PROFILE_DEEPER_REVIEW,
    ANALYSIS_PROFILE_CUSTOM,
]);
const DEFAULT_ANALYSIS_THRESHOLDS = Object.freeze({
    minLoc: 10,
    minStmt: 6,
    blockMinLoc: 20,
    blockMinStmt: 8,
    segmentMinLoc: 20,
    segmentMinStmt: 10,
});
const DEEP_REVIEW_ANALYSIS_THRESHOLDS = Object.freeze({
    minLoc: 5,
    minStmt: 2,
    blockMinLoc: 5,
    blockMinStmt: 2,
    segmentMinLoc: 5,
    segmentMinStmt: 2,
});

function signedInteger(value) {
    if (typeof value !== "number" || Number.isNaN(value)) {
        return "0";
    }
    return value > 0 ? `+${value}` : String(value);
}

function parseUtcTimestamp(value) {
    if (!value) {
        return null;
    }
    const parsed = Date.parse(String(value));
    return Number.isNaN(parsed) ? null : parsed;
}

function revealLineSpan(line, endLine, lineCount) {
    if (
        typeof line !== "number" ||
        !Number.isFinite(line) ||
        typeof lineCount !== "number" ||
        !Number.isFinite(lineCount) ||
        lineCount < 1
    ) {
        return null;
    }
    const lastDocumentLine = Math.max(Math.trunc(lineCount) - 1, 0);
    const startLine = Math.min(Math.max(Math.trunc(line) - 1, 0), lastDocumentLine);
    const requestedEndLine =
        typeof endLine === "number" && Number.isFinite(endLine)
            ? Math.trunc(endLine) - 1
            : startLine;
    const finalLine = Math.min(
        Math.max(requestedEndLine, startLine),
        lastDocumentLine
    );
    return {startLine, finalLine};
}

function locationsNeedDetailHydration(value) {
    if (!Array.isArray(value) || value.length === 0) {
        return true;
    }
    return value.some((entry) => {
        if (typeof entry === "string") {
            return true;
        }
        if (!entry || typeof entry !== "object") {
            return true;
        }
        return typeof entry.end_line !== "number";
    });
}

function staleMessage(reason) {
    if (reason === STALE_REASON_EDITOR) {
        return "Review data may be stale because there are unsaved editor changes.";
    }
    return "Review data may be stale because the workspace changed after this run.";
}

function normalizedLaunchSpec(spec) {
    const command = String(spec?.command || "").trim();
    if (!command) {
        throw new Error("CodeClone MCP launcher command must not be empty.");
    }
    const args = Array.isArray(spec?.args)
        ? spec.args
            .filter((value) => typeof value === "string")
            .map((value) => value.trim())
            .filter(Boolean)
        : [];
    const cwd = String(spec?.cwd || "").trim();
    if (!cwd) {
        throw new Error("CodeClone MCP launcher cwd must not be empty.");
    }
    const source = String(spec?.source || "").trim();
    return {command, args, cwd, source};
}

function trimTail(value, maxChars) {
    const text = String(value || "");
    if (!Number.isFinite(maxChars) || maxChars < 1) {
        return "";
    }
    return text.length <= maxChars ? text : text.slice(-maxChars);
}

function resolveWorkspacePath(rootPath, relativePath) {
    const root = String(rootPath || "").trim();
    const candidate = String(relativePath || "").trim();
    if (!root || !candidate) {
        return null;
    }
    const resolved = path.resolve(root, candidate);
    const relativeToRoot = path.relative(root, resolved);
    if (
        relativeToRoot === "" ||
        (!relativeToRoot.startsWith("..") && !path.isAbsolute(relativeToRoot))
    ) {
        return resolved;
    }
    return null;
}

function workspaceLocalLauncherCandidates(
    rootPath,
    platform = process.platform
) {
    const root = String(rootPath || "").trim();
    if (!root) {
        return [];
    }
    const platformPath = platform === "win32" ? path.win32 : path.posix;
    if (platform === "win32") {
        return [
            platformPath.join(root, ".venv", "Scripts", "codeclone-mcp.exe"),
            platformPath.join(root, ".venv", "Scripts", "codeclone-mcp.cmd"),
            platformPath.join(root, "venv", "Scripts", "codeclone-mcp.exe"),
            platformPath.join(root, "venv", "Scripts", "codeclone-mcp.cmd"),
        ];
    }
    return [
        platformPath.join(root, ".venv", "bin", "codeclone-mcp"),
        platformPath.join(root, "venv", "bin", "codeclone-mcp"),
    ];
}

function normalizeAnalysisProfile(value) {
    const profileId = String(value || "").trim();
    return ANALYSIS_PROFILE_IDS.has(profileId)
        ? profileId
        : ANALYSIS_PROFILE_DEFAULTS;
}

function parseCodeCloneVersion(value) {
    const text = String(value || "").trim();
    const match = text.match(/(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?/);
    if (!match) {
        return null;
    }
    return {
        major: Number.parseInt(match[1], 10),
        minor: Number.parseInt(match[2], 10),
        patch: Number.parseInt(match[3], 10),
        prereleaseTag: match[4] || "",
        prereleaseNumber: match[5] ? Number.parseInt(match[5], 10) : 0,
        text: match[0],
    };
}

function compareCodeCloneVersions(left, right) {
    const leftVersion = parseCodeCloneVersion(left);
    const rightVersion = parseCodeCloneVersion(right);
    if (!leftVersion || !rightVersion) {
        return null;
    }
    const fields = ["major", "minor", "patch"];
    for (const field of fields) {
        if (leftVersion[field] !== rightVersion[field]) {
            return leftVersion[field] - rightVersion[field];
        }
    }
    const prereleaseRank = {
        a: 0,
        b: 1,
        rc: 2,
        "": 3,
    };
    if (leftVersion.prereleaseTag !== rightVersion.prereleaseTag) {
        return (
            prereleaseRank[leftVersion.prereleaseTag] -
            prereleaseRank[rightVersion.prereleaseTag]
        );
    }
    return leftVersion.prereleaseNumber - rightVersion.prereleaseNumber;
}

function isMinimumSupportedCodeCloneVersion(
    value,
    minimum = MINIMUM_SUPPORTED_CODECLONE_VERSION
) {
    const comparison = compareCodeCloneVersions(value, minimum);
    return comparison !== null && comparison >= 0;
}

function launchSpecOrigin(spec) {
    const launchSpec = spec || {};
    const command = String(launchSpec.command || "").trim() || "codeclone-mcp";
    const args = Array.isArray(launchSpec.args)
        ? launchSpec.args.filter((value) => typeof value === "string" && value.trim())
        : [];
    const renderedCommand = args.length > 0 ? `${command} ${args.join(" ")}` : command;
    switch (String(launchSpec.source || "").trim()) {
        case "workspaceLocal":
            return `workspace-local launcher (${renderedCommand})`;
        case "configured":
            return `configured launcher (${renderedCommand})`;
        case "uvFallback":
            return `repo-local uv fallback (${renderedCommand})`;
        case "path":
        default:
            return `PATH launcher (${renderedCommand})`;
    }
}

function unsupportedVersionMessage(
    reportedVersion,
    minimum = MINIMUM_SUPPORTED_CODECLONE_VERSION,
    launchSpec = null
) {
    const actualVersion = String(reportedVersion || "unknown");
    return (
        `The local CodeClone MCP server is not supported. It reported version ` +
        `${actualVersion}; this extension requires CodeClone >= ${minimum}. ` +
        `The extension resolved ${launchSpecOrigin(launchSpec)}. ` +
        `Update that environment or set codeclone.mcp.command to a newer launcher.`
    );
}

function nonNegativeInteger(value, fallback) {
    const parsed =
        typeof value === "number" && Number.isFinite(value)
            ? Math.trunc(value)
            : Number.parseInt(String(value ?? ""), 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function customAnalysisThresholds(value = {}) {
    return {
        minLoc: nonNegativeInteger(value.minLoc, DEFAULT_ANALYSIS_THRESHOLDS.minLoc),
        minStmt: nonNegativeInteger(
            value.minStmt,
            DEFAULT_ANALYSIS_THRESHOLDS.minStmt
        ),
        blockMinLoc: nonNegativeInteger(
            value.blockMinLoc,
            DEFAULT_ANALYSIS_THRESHOLDS.blockMinLoc
        ),
        blockMinStmt: nonNegativeInteger(
            value.blockMinStmt,
            DEFAULT_ANALYSIS_THRESHOLDS.blockMinStmt
        ),
        segmentMinLoc: nonNegativeInteger(
            value.segmentMinLoc,
            DEFAULT_ANALYSIS_THRESHOLDS.segmentMinLoc
        ),
        segmentMinStmt: nonNegativeInteger(
            value.segmentMinStmt,
            DEFAULT_ANALYSIS_THRESHOLDS.segmentMinStmt
        ),
    };
}

function analysisThresholdOverrides(thresholds) {
    return {
        min_loc: thresholds.minLoc,
        min_stmt: thresholds.minStmt,
        block_min_loc: thresholds.blockMinLoc,
        block_min_stmt: thresholds.blockMinStmt,
        segment_min_loc: thresholds.segmentMinLoc,
        segment_min_stmt: thresholds.segmentMinStmt,
    };
}

function formatAnalysisThresholdSummary(profileId, thresholds) {
    switch (profileId) {
        case ANALYSIS_PROFILE_DEFAULTS:
            return "Repo defaults / pyproject";
        case ANALYSIS_PROFILE_DEEPER_REVIEW:
            return "5/2 across functions, blocks, and segments";
        default:
            return (
                `func ${thresholds.minLoc}/${thresholds.minStmt} · ` +
                `block ${thresholds.blockMinLoc}/${thresholds.blockMinStmt} · ` +
                `seg ${thresholds.segmentMinLoc}/${thresholds.segmentMinStmt}`
            );
    }
}

function resolveAnalysisSettings(value = {}) {
    const profileId = normalizeAnalysisProfile(value.profile);
    const thresholds =
        profileId === ANALYSIS_PROFILE_DEEPER_REVIEW
            ? {...DEEP_REVIEW_ANALYSIS_THRESHOLDS}
            : customAnalysisThresholds(value);
    const label =
        profileId === ANALYSIS_PROFILE_DEFAULTS
            ? "Conservative"
            : profileId === ANALYSIS_PROFILE_DEEPER_REVIEW
                ? "Deeper review"
                : "Custom";
    const detail =
        profileId === ANALYSIS_PROFILE_DEFAULTS
            ? "Use repo defaults or pyproject for the first pass."
            : profileId === ANALYSIS_PROFILE_DEEPER_REVIEW
                ? "Lower thresholds for a deliberate second pass on smaller units."
                : "Use the explicit threshold settings from this workspace.";
    return {
        profileId,
        label,
        detail,
        thresholds,
        thresholdSummary: formatAnalysisThresholdSummary(profileId, thresholds),
        overrides:
            profileId === ANALYSIS_PROFILE_DEFAULTS
                ? {}
                : analysisThresholdOverrides(thresholds),
    };
}

function sameAnalysisSettings(left, right) {
    if (!left || !right) {
        return false;
    }
    return JSON.stringify(left) === JSON.stringify(right);
}

module.exports = {
    ANALYSIS_PROFILE_CUSTOM,
    ANALYSIS_PROFILE_DEEPER_REVIEW,
    ANALYSIS_PROFILE_DEFAULTS,
    DEFAULT_ANALYSIS_THRESHOLDS,
    DEEP_REVIEW_ANALYSIS_THRESHOLDS,
    MINIMUM_SUPPORTED_CODECLONE_VERSION,
    PREVIEW_INSTALL_COMMAND,
    STALE_REASON_EDITOR,
    STALE_REASON_WORKSPACE,
    analysisThresholdOverrides,
    compareCodeCloneVersions,
    customAnalysisThresholds,
    isMinimumSupportedCodeCloneVersion,
    launchSpecOrigin,
    locationsNeedDetailHydration,
    normalizedLaunchSpec,
    normalizeAnalysisProfile,
    parseUtcTimestamp,
    parseCodeCloneVersion,
    revealLineSpan,
    resolveWorkspacePath,
    resolveAnalysisSettings,
    sameAnalysisSettings,
    signedInteger,
    staleMessage,
    trimTail,
    unsupportedVersionMessage,
    workspaceLocalLauncherCandidates,
};
