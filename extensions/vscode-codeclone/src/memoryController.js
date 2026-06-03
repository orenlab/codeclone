"use strict";

/** @type {any} */
const vscode = require("vscode");

const {
    commitGovernance,
    ensureIdeGovernanceRegistered,
    prepareGovernance,
} = require("./memoryGovernance");
const {MCPClientError} = require("./mcpClient");
const {safeArray, safeObject} = require("./formatters");

const MEMORY_CACHE_TTL_MS = 15_000;

class MemoryController {
    /**
     * @param {object} extension
     */
    constructor(extension) {
        this.extension = extension;
        /** @type {Map<string, {loadedAt: number, connected: boolean, memorySupported: boolean, status: object|null, drafts: object[], stale: object[]}>} */
        this.cacheByRoot = new Map();
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     */
    workspaceKey(folder) {
        return folder.uri.toString();
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     */
    async ensureSnapshot(folder) {
        const key = this.workspaceKey(folder);
        const cached = this.cacheByRoot.get(key);
        const now = Date.now();
        if (cached && now - cached.loadedAt < MEMORY_CACHE_TTL_MS) {
            return cached;
        }
        // The Memory view reflects the current connection — it never starts
        // the local server from a tree render. Auto-connecting here would
        // surface connect-time prompts and local-store records on restart
        // simply because the view was expanded. When disconnected, return an
        // empty snapshot and let the view-welcome content guide the user.
        if (!this.extension.client.isConnected()) {
            const snapshot = {
                loadedAt: now,
                connected: false,
                memorySupported: true,
                status: null,
                drafts: [],
                stale: [],
            };
            this.cacheByRoot.set(key, snapshot);
            return snapshot;
        }
        // Engineering Memory tools exist only on CodeClone 2.1.0a1+. The
        // extension's minimum-version gate (2.0.0) still admits older servers,
        // so detect the capability from the connected server's advertised tool
        // list rather than guessing from a version string. Without this, the
        // Memory view would call missing tools and surface a misleading
        // "not initialized" state on older servers.
        const toolNames = safeArray(
            this.extension.client.getConnectionSnapshot().toolNames
        ).map((name) => String(name));
        if (!toolNames.includes("query_engineering_memory")) {
            const snapshot = {
                loadedAt: now,
                connected: true,
                memorySupported: false,
                status: null,
                drafts: [],
                stale: [],
            };
            this.cacheByRoot.set(key, snapshot);
            return snapshot;
        }
        const root = folder.uri.fsPath;
        const client = this.extension.client;
        let status = null;
        let drafts = [];
        let stale = [];
        try {
            const statusPayload = await client.callTool("query_engineering_memory", {
                root,
                mode: "status",
            });
            status = safeObject(statusPayload.payload);
        } catch {
            status = null;
        }
        try {
            const draftsPayload = await client.callTool("query_engineering_memory", {
                root,
                mode: "drafts",
                max_results: 50,
            });
            drafts = safeArray(safeObject(draftsPayload.payload).records);
        } catch {
            drafts = [];
        }
        try {
            const stalePayload = await client.callTool("query_engineering_memory", {
                root,
                mode: "stale",
                max_results: 50,
            });
            stale = safeArray(safeObject(stalePayload.payload).records);
        } catch {
            stale = [];
        }
        const snapshot = {
            loadedAt: now,
            connected: true,
            memorySupported: true,
            status,
            drafts,
            stale,
        };
        this.cacheByRoot.set(key, snapshot);
        return snapshot;
    }

    invalidate(folder) {
        if (folder) {
            this.cacheByRoot.delete(this.workspaceKey(folder));
            return;
        }
        this.cacheByRoot.clear();
    }

    /**
     * @param {import("vscode").WorkspaceFolder | undefined} folder
     * @param {object|undefined} node
     */
    async getChildren(folder, node) {
        // Empty states (no folder / untrusted / disconnected) are handled by
        // the view-welcome content in package.json, keeping the Memory view
        // consistent with the other CodeClone views. Returning [] lets that
        // guidance render instead of ad-hoc message rows.
        if (!folder || !vscode.workspace.isTrusted) {
            return [];
        }
        const snapshot = await this.ensureSnapshot(folder);
        if (!snapshot.connected) {
            return [];
        }
        if (!snapshot.memorySupported) {
            if (node) {
                return [];
            }
            return [
                {
                    nodeType: "message",
                    label: "Engineering Memory requires CodeClone 2.1.0a1 or newer.",
                    icon: new vscode.ThemeIcon("info"),
                },
            ];
        }
        if (!node) {
            const children = [
                {
                    nodeType: "section",
                    id: "memory-status",
                    label: "Status",
                    icon: new vscode.ThemeIcon("database"),
                    contextValue: "codeclone.memorySection",
                },
                {
                    nodeType: "section",
                    id: "memory-inbox",
                    label: "Inbox",
                    description:
                        snapshot.drafts.length > 0
                            ? `${snapshot.drafts.length} draft`
                            : "empty",
                    icon: new vscode.ThemeIcon("inbox"),
                    contextValue: "codeclone.memorySection",
                },
                {
                    nodeType: "section",
                    id: "memory-stale",
                    label: "Stale",
                    description:
                        snapshot.stale.length > 0
                            ? `${snapshot.stale.length}`
                            : undefined,
                    icon: new vscode.ThemeIcon("history"),
                    contextValue: "codeclone.memorySection",
                },
                {
                    nodeType: "section",
                    id: "memory-actions",
                    label: "Actions",
                    icon: new vscode.ThemeIcon("settings-gear"),
                    contextValue: "codeclone.memorySection",
                },
            ];
            return children;
        }
        if (node.nodeType === "section") {
            if (node.id === "memory-status") {
                if (!snapshot.status) {
                    return [
                        {
                            nodeType: "message",
                            label: "Memory database not initialized. Run analysis first.",
                            icon: new vscode.ThemeIcon("info"),
                        },
                    ];
                }
                const lines = [
                    `Backend: ${snapshot.status.backend || "unknown"}`,
                    `Records: ${snapshot.status.record_count ?? "—"}`,
                    `Drafts: ${snapshot.status.draft_count ?? snapshot.drafts.length}`,
                    `Active: ${snapshot.status.active_count ?? "—"}`,
                ];
                return lines.map((label) => ({
                    nodeType: "detail",
                    label,
                    icon: new vscode.ThemeIcon("circle-outline"),
                }));
            }
            if (node.id === "memory-inbox") {
                if (!snapshot.drafts.length) {
                    return [
                        {
                            nodeType: "message",
                            label: "No draft records in the inbox.",
                            icon: new vscode.ThemeIcon("check"),
                        },
                    ];
                }
                return snapshot.drafts.map((record) => this._draftNode(record));
            }
            if (node.id === "memory-stale") {
                if (!snapshot.stale.length) {
                    return [
                        {
                            nodeType: "message",
                            label: "No stale records.",
                            icon: new vscode.ThemeIcon("check"),
                        },
                    ];
                }
                return snapshot.stale.map((record) => this._staleNode(record));
            }
            if (node.id === "memory-actions") {
                return [
                    {
                        nodeType: "action",
                        id: "refresh-memory",
                        label: "Refresh memory",
                        icon: new vscode.ThemeIcon("refresh"),
                        command: {
                            command: "codeclone.refreshMemory",
                            title: "Refresh Memory",
                        },
                    },
                    {
                        nodeType: "action",
                        id: "sync-from-run",
                        label: "Sync from latest run",
                        icon: new vscode.ThemeIcon("cloud-download"),
                        command: {
                            command: "codeclone.syncMemoryFromRun",
                            title: "Sync Memory From Run",
                        },
                    },
                ];
            }
        }
        if (node.nodeType === "memoryDraft" && node.record) {
            return this._recordActionChildren(node, {includeReject: true});
        }
        if (node.nodeType === "memoryStale" && node.record) {
            // Stale records can be re-verified (approve) once the linked code
            // is confirmed, or inspected. Reject is reserved for drafts.
            return this._recordActionChildren(node, {includeReject: false});
        }
        return [];
    }

    /**
     * Build the expandable action rows shared by draft and stale records.
     *
     * @param {object} node
     * @param {{includeReject: boolean}} options
     */
    _recordActionChildren(node, {includeReject}) {
        const children = [
            {
                nodeType: "detail",
                label: String(recordStatement(node.record)),
                icon: new vscode.ThemeIcon("note"),
            },
            {
                nodeType: "action",
                id: "approve",
                label: "Approve",
                icon: new vscode.ThemeIcon("check"),
                command: {
                    command: "codeclone.approveMemoryRecord",
                    title: "Approve Memory Record",
                    arguments: [node],
                },
            },
        ];
        if (includeReject) {
            children.push({
                nodeType: "action",
                id: "reject",
                label: "Reject",
                icon: new vscode.ThemeIcon("close"),
                command: {
                    command: "codeclone.rejectMemoryRecord",
                    title: "Reject Memory Record",
                    arguments: [node],
                },
            });
        }
        children.push({
            nodeType: "action",
            id: "open-detail",
            label: "Open detail",
            icon: new vscode.ThemeIcon("open-preview"),
            command: {
                command: "codeclone.openMemoryRecord",
                title: "Open Memory Record",
                arguments: [node],
            },
        });
        return children;
    }

    /**
     * @param {object} record
     */
    _draftNode(record) {
        const statement = recordStatement(record);
        const label =
            statement.length > 72 ? `${statement.slice(0, 69)}…` : statement;
        const node = {
            nodeType: "memoryDraft",
            id: `memory-draft-${String(record.id || "unknown")}`,
            record,
            label: label || String(record.id || "draft"),
            description: String(record.type || "record"),
            tooltip: statement,
            icon: new vscode.ThemeIcon("git-pull-request"),
            contextValue: "codeclone.memoryDraft",
        };
        node.command = {
            command: "codeclone.openMemoryRecord",
            title: "Open Memory Record",
            arguments: [node],
        };
        return node;
    }

    /**
     * @param {object} record
     */
    _staleNode(record) {
        const statement = recordStatement(record);
        const label =
            statement.length > 72 ? `${statement.slice(0, 69)}…` : statement;
        const node = {
            nodeType: "memoryStale",
            id: `memory-stale-${String(record.id || "unknown")}`,
            record,
            label: label || String(record.id || "stale"),
            description: String(record.type || "record"),
            tooltip: statement,
            icon: new vscode.ThemeIcon("history"),
            contextValue: "codeclone.memoryStale",
        };
        node.command = {
            command: "codeclone.openMemoryRecord",
            title: "Open Memory Record",
            arguments: [node],
        };
        return node;
    }

    /**
     * Execute an already-confirmed governance decision. The caller is
     * responsible for validating status and confirming with the user
     * *before* invoking this — keeping the confirmation out of any progress
     * notification. Reports "Preparing…"/"Committing…" through `progress`.
     *
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {object} node
     * @param {"approve"|"reject"|"archive"} decision
     * @param {{progress?: {report: Function}, token?: {isCancellationRequested: boolean}}} [options]
     */
    async runGovernance(folder, node, decision, options = {}) {
        const {progress, token} = options;
        const record = safeObject(node.record);
        const recordId = String(record.id || "");
        if (!recordId) {
            throw new Error("Memory record is missing an id.");
        }
        this.assertGovernanceAllowed(String(record.status || "draft"), decision);
        const root = folder.uri.fsPath;
        const client = this.extension.client;
        if (token?.isCancellationRequested) {
            return null;
        }
        progress?.report({message: "Preparing…"});
        const prepared = await this._prepareGovernanceWithRetry(
            client,
            root,
            recordId,
            decision
        );
        if (token?.isCancellationRequested) {
            return null;
        }
        if (prepared.status === "not_found") {
            throw new Error(`Memory record not found: ${recordId}`);
        }
        if (prepared.status === "rejected") {
            const nextStep = prepared.next_step ? ` ${prepared.next_step}` : "";
            throw new MCPClientError(
                `${prepared.message || "Governance is not available."}${nextStep}`
            );
        }
        progress?.report({message: "Committing…"});
        const actor = vscode.env.userName || "vscode-user";
        const committed = await commitGovernance(
            client,
            this.extension.context,
            prepared,
            root,
            actor,
            decision
        );
        if (committed.status === "rejected") {
            const nextStep = committed.next_step ? ` ${committed.next_step}` : "";
            throw new MCPClientError(
                `${committed.message || "Governance commit was rejected."}${nextStep}`
            );
        }
        this.invalidate(folder);
        return committed;
    }

    /**
     * Prepare a governance ticket. The IDE governance key is registered once
     * on connect; only re-register (and retry) if the server reports that the
     * session key went missing — e.g. after a server restart — instead of
     * paying a registration round-trip on every decision.
     *
     * @param {import("./mcpClient").CodeCloneMcpClient} client
     * @param {string} root
     * @param {string} recordId
     * @param {"approve"|"reject"|"archive"} decision
     */
    async _prepareGovernanceWithRetry(client, root, recordId, decision) {
        const prepared = await prepareGovernance(client, root, recordId, decision);
        if (
            prepared.status === "rejected" &&
            prepared.reason === "governance_key_missing"
        ) {
            await ensureIdeGovernanceRegistered(
                client,
                this.extension.context,
                root
            );
            return prepareGovernance(client, root, recordId, decision);
        }
        return prepared;
    }

    /**
     * @param {string} status
     * @param {"approve"|"reject"|"archive"} decision
     */
    assertGovernanceAllowed(status, decision) {
        if (decision === "approve" && status === "active") {
            throw new Error("This memory record is already active.");
        }
        if (decision === "approve" && status === "rejected") {
            throw new Error("Rejected records cannot be approved. Create a new draft.");
        }
        if (decision === "reject" && status !== "draft") {
            throw new Error(`Only draft records can be rejected (status: ${status}).`);
        }
        if (decision === "archive" && status !== "active") {
            throw new Error(`Only active records can be archived (status: ${status}).`);
        }
        if (
            decision === "approve" &&
            status !== "draft" &&
            status !== "stale"
        ) {
            throw new Error(`Cannot approve a record in status '${status}'.`);
        }
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {object} node
     */
    /**
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {string} recordId
     */
    async fetchRecordById(folder, recordId) {
        const root = folder.uri.fsPath;
        const response = await this.extension.client.callTool(
            "query_engineering_memory",
            {
                root,
                mode: "get",
                record_id: recordId,
            }
        );
        const body = safeObject(safeObject(response).payload);
        if (String(response.status || "") === "not_found" || !body.record) {
            throw new Error(`Memory record not found: ${recordId}`);
        }
        return safeObject(body.record);
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {object} node
     */
    async openRecordDetail(folder, node) {
        const record = safeObject(node.record);
        const subjects = safeArray(record.subjects)
            .map(
                (item) =>
                    `- ${item.subject_kind || item.subject_nodeType || "subject"}: ${item.subject_key} (${item.relation || "primary"})`
            )
            .join("\n");
        const body = [
            `# ${record.type || "memory"}`,
            "",
            `**Status:** ${record.status || "unknown"}`,
            `**Confidence:** ${record.confidence || "—"}`,
            "",
            recordStatement(record),
            "",
            subjects ? `## Subjects\n${subjects}` : "",
        ]
            .filter(Boolean)
            .join("\n");
        const doc = await vscode.workspace.openTextDocument({
            language: "markdown",
            content: body,
        });
        await vscode.window.showTextDocument(doc, {preview: true});
    }

    draftCount(folder) {
        const cached = this.cacheByRoot.get(this.workspaceKey(folder));
        return cached ? cached.drafts.length : 0;
    }
}

/**
 * @param {object} record
 */
function recordStatement(record) {
    return String(record.statement || "").trim();
}

module.exports = {
    MemoryController,
    recordStatement,
};
