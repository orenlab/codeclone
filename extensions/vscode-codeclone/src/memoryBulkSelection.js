"use strict";

const DRAFT_TREE_ID_PREFIX = "memory-draft-";
const STALE_TREE_ID_PREFIX = "memory-stale-";

/**
 * @param {object} record
 * @returns {string}
 */
function recordStatement(record) {
    return String(record?.statement || "").trim();
}

/**
 * @param {string|undefined} treeItemId
 * @returns {string}
 */
function recordIdFromTreeItemId(treeItemId) {
    const id = String(treeItemId || "");
    if (id.startsWith(DRAFT_TREE_ID_PREFIX)) {
        return id.slice(DRAFT_TREE_ID_PREFIX.length);
    }
    if (id.startsWith(STALE_TREE_ID_PREFIX)) {
        return id.slice(STALE_TREE_ID_PREFIX.length);
    }
    return "";
}

/**
 * @param {string} recordId
 * @param {"memoryDraft"|"memoryStale"} nodeType
 * @returns {string}
 */
function treeItemIdForGovernanceNode(recordId, nodeType) {
    const prefix =
        nodeType === "memoryStale" ? STALE_TREE_ID_PREFIX : DRAFT_TREE_ID_PREFIX;
    return `${prefix}${recordId}`;
}

/**
 * @param {object|undefined} node
 * @returns {string}
 */
function recordIdFromGovernanceNode(node) {
    if (!node) {
        return "";
    }
    if (node.nodeType === "memoryDraft" || node.nodeType === "memoryStale") {
        return String(node.record?.id || "");
    }
    return "";
}

/** @deprecated Use recordIdFromGovernanceNode */
function recordIdFromDraftNode(node) {
    return recordIdFromGovernanceNode(node);
}

/**
 * @param {object[]} nodes
 * @returns {object[]}
 */
function dedupeGovernanceNodes(nodes) {
    const seen = new Set();
    const result = [];
    for (const node of nodes) {
        const id = recordIdFromGovernanceNode(node);
        if (!id || seen.has(id)) {
            continue;
        }
        seen.add(id);
        result.push(node);
    }
    return result;
}

/** @deprecated Use dedupeGovernanceNodes */
function dedupeDraftNodes(nodes) {
    return dedupeGovernanceNodes(nodes);
}

/**
 * @param {string} treeItemId
 * @returns {"memoryDraft"|"memoryStale"|null}
 */
function governanceNodeTypeFromTreeItemId(treeItemId) {
    const id = String(treeItemId || "");
    if (id.startsWith(DRAFT_TREE_ID_PREFIX)) {
        return "memoryDraft";
    }
    if (id.startsWith(STALE_TREE_ID_PREFIX)) {
        return "memoryStale";
    }
    return null;
}

/**
 * Resolve governance targets from a primary tree/command node and optional
 * multi-select tree items from `canSelectMany`.
 *
 * @param {object|undefined} primary
 * @param {object[]|undefined} selectedItems
 * @returns {object[]}
 */
function resolveGovernanceTargets(primary, selectedItems) {
    const candidates = [];
    if (Array.isArray(selectedItems) && selectedItems.length > 0) {
        for (const item of selectedItems) {
            const id = recordIdFromTreeItemId(item?.id);
            const nodeType = governanceNodeTypeFromTreeItemId(item?.id);
            if (!id || !nodeType) {
                continue;
            }
            candidates.push({
                nodeType,
                id: treeItemIdForGovernanceNode(id, nodeType),
                record: {id},
            });
        }
    } else if (primary) {
        candidates.push(primary);
    }
    return dedupeGovernanceNodes(candidates);
}

/**
 * @param {object[]} nodes
 * @param {"approve"|"reject"|"archive"} decision
 * @param {number} [previewLimit]
 * @returns {string}
 */
function buildBulkConfirmDetail(nodes, decision, previewLimit = 3) {
    const lines = nodes.slice(0, previewLimit).map((node) => {
        const id = recordIdFromGovernanceNode(node);
        const statement = recordStatement(node.record || {});
        const type = String(node.record?.type || "record");
        const preview =
            statement.length > 120 ? `${statement.slice(0, 117)}…` : statement;
        return `• [${type}] ${preview || id}`;
    });
    if (nodes.length > previewLimit) {
        lines.push(`…and ${nodes.length - previewLimit} more`);
    }
    const verb =
        decision === "reject"
            ? "Rejected drafts are removed from the inbox."
            : "Approved records become active engineering memory.";
    return [...lines, "", verb].join("\n");
}

/**
 * @param {{succeeded: string[], failed: {recordId: string, message: string}[]}} results
 * @param {"approve"|"reject"|"archive"} decision
 * @returns {string}
 */
function formatBulkResultSummary(results, decision) {
    const past =
        decision === "reject"
            ? "rejected"
            : decision === "archive"
              ? "archived"
              : "approved";
    const parts = [];
    if (results.succeeded.length) {
        parts.push(
            `${results.succeeded.length} memory record(s) ${past}.`
        );
    }
    if (results.failed.length) {
        const failedIds = results.failed
            .slice(0, 3)
            .map((item) => item.recordId)
            .join(", ");
        const suffix =
            results.failed.length > 3
                ? ` (+${results.failed.length - 3} more)`
                : "";
        parts.push(
            `${results.failed.length} failed: ${failedIds}${suffix}.`
        );
    }
    return parts.join(" ");
}

/**
 * @param {object[]} records
 * @returns {string[]}
 */
function distinctRecordTypes(records) {
    const types = new Set();
    for (const record of records) {
        const type = String(record?.type || "").trim();
        if (type) {
            types.add(type);
        }
    }
    return [...types].sort();
}

/** @deprecated Use distinctRecordTypes */
function distinctDraftTypes(drafts) {
    return distinctRecordTypes(drafts);
}

module.exports = {
    DRAFT_TREE_ID_PREFIX,
    STALE_TREE_ID_PREFIX,
    recordIdFromTreeItemId,
    recordIdFromGovernanceNode,
    recordIdFromDraftNode,
    dedupeGovernanceNodes,
    dedupeDraftNodes,
    resolveGovernanceTargets,
    buildBulkConfirmDetail,
    formatBulkResultSummary,
    distinctRecordTypes,
    distinctDraftTypes,
    governanceNodeTypeFromTreeItemId,
    treeItemIdForGovernanceNode,
};
