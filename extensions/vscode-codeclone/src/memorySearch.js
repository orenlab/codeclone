"use strict";

/** @type {any} */
const vscode = require("vscode");

const {safeArray, safeObject, workspaceRelativePath} = require("./formatters");
const {recordStatement} = require("./memoryController");

const MEMORY_SEARCH_MAX_QUERY = 200;
const MEMORY_SEARCH_MIN_QUERY = 2;
const MEMORY_RECORD_ID_PATTERN = /^mem-[0-9a-f]{32}$/;

const DEFAULT_SEARCH_OPTIONS = {
    semantic: true,
    includeDrafts: false,
    includeStale: false,
    maxResults: 20,
    detailLevel: "compact",
};

/**
 * @param {string} query
 * @returns {string|null}
 */
function sanitizeSearchQuery(query) {
    const trimmed = String(query || "").trim();
    if (trimmed.length < MEMORY_SEARCH_MIN_QUERY) {
        return `Enter at least ${MEMORY_SEARCH_MIN_QUERY} characters.`;
    }
    if (trimmed.length > MEMORY_SEARCH_MAX_QUERY) {
        return `Query must be at most ${MEMORY_SEARCH_MAX_QUERY} characters.`;
    }
    if (/[\u0000-\u001f\u007f]/.test(trimmed)) {
        return "Query contains unsupported control characters.";
    }
    return null;
}

/**
 * @param {string} recordId
 */
function isValidMemoryRecordId(recordId) {
    return MEMORY_RECORD_ID_PATTERN.test(String(recordId || ""));
}

/**
 * @param {string} rawPath
 * @returns {string|null}
 */
function normalizeMemorySearchPath(rawPath) {
    const text = String(rawPath || "").replace(/\\/g, "/").trim().replace(/^\.\//, "");
    if (!text || text === "." || text === "..") {
        return null;
    }
    if (text.startsWith("/") || /^[a-zA-Z]:/.test(text)) {
        return null;
    }
    if (text.split("/").includes("..")) {
        return null;
    }
    return text;
}

/**
 * @param {import("vscode").WorkspaceFolder | null | undefined} folder
 * @returns {string|null}
 */
function activeEditorMemoryPath(folder) {
    const editor = vscode.window.activeTextEditor;
    if (!editor || !folder) {
        return null;
    }
    const docFolder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
    if (!docFolder || docFolder.uri.toString() !== folder.uri.toString()) {
        return null;
    }
    if (editor.document.uri.scheme !== "file") {
        return null;
    }
    const rel = workspaceRelativePath(folder, editor.document.uri.fsPath);
    return normalizeMemorySearchPath(rel);
}

/**
 * @param {import("vscode").WorkspaceConfiguration} config
 */
function readMemorySearchSettings(config) {
    return {
        semantic: config.get("codeclone.memory.searchSemantic", DEFAULT_SEARCH_OPTIONS.semantic),
        includeDrafts: config.get(
            "codeclone.memory.searchIncludeDrafts",
            DEFAULT_SEARCH_OPTIONS.includeDrafts
        ),
        includeStale: config.get(
            "codeclone.memory.searchIncludeStale",
            DEFAULT_SEARCH_OPTIONS.includeStale
        ),
        maxResults: Math.min(
            50,
            Math.max(5, Number(config.get("codeclone.memory.searchMaxResults", 20)) || 20)
        ),
        detailLevel:
            String(config.get("codeclone.memory.searchDetailLevel", "compact")) ===
            "full"
                ? "full"
                : "compact",
    };
}

/**
 * @param {string} root
 * @param {string} query
 * @param {object} options
 */
function buildSearchToolArgs(root, query, options) {
    return {
        root,
        mode: "search",
        query,
        semantic: Boolean(options.semantic),
        include_drafts: Boolean(options.includeDrafts),
        include_stale: Boolean(options.includeStale),
        max_results: options.maxResults,
        detail_level: options.detailLevel,
    };
}

/**
 * @param {string} root
 * @param {string} path
 * @param {object} options
 */
function buildForPathToolArgs(root, path, options) {
    return {
        root,
        mode: "for_path",
        path,
        include_stale: Boolean(options.includeStale),
        max_results: options.maxResults,
        detail_level: options.detailLevel,
    };
}

/**
 * @param {object} semantic
 */
function formatSemanticStatusLine(semantic) {
    const block = safeObject(semantic);
    if (!block || Object.keys(block).length === 0) {
        return "Semantic recall: off";
    }
    if (block.used) {
        const provider = block.provider || block.backend || "provider";
        const model = block.model ? ` · ${block.model}` : "";
        return `Semantic recall: on (${provider}${model})`;
    }
    const reason = block.reason || "unavailable";
    return `Semantic recall: off (${reason})`;
}

/**
 * @param {object} record
 * @param {number} index
 */
function recordToQuickPickItem(record, index) {
    const item = safeObject(record);
    const id = String(item.id || "");
    const type = String(item.type || "memory");
    const status = String(item.status || "unknown");
    const statement = recordStatement(item);
    const preview =
        statement.length > 120 ? `${statement.slice(0, 117)}…` : statement;
    const subjects = safeArray(item.subjects)
        .map((s) => safeObject(s).subject_key)
        .filter(Boolean)
        .slice(0, 2);
    const subjectHint = subjects.length > 0 ? ` · ${subjects.join(", ")}` : "";
    return {
        label: `${type} · ${status}`,
        description: id,
        detail: `${preview}${subjectHint}`,
        record: item,
        index,
    };
}

/**
 * @param {string} recordId
 */
function memoryRecordCommandUri(recordId) {
    const encoded = encodeURIComponent(JSON.stringify([recordId]));
    return `command:codeclone.openMemoryRecordById?${encoded}`;
}

class MemorySearchController {
    /**
     * @param {object} extension
     */
    constructor(extension) {
        this.extension = extension;
        /** @type {import("vscode").WebviewPanel | null} */
        this.activePanel = null;
        /** @type {{folderKey: string, query: string, folder: import("vscode").WorkspaceFolder, result: object, relPath?: string|null} | null} */
        this.activeSession = null;
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     */
    sessionKey(folder) {
        return folder.uri.toString();
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     */
    async ensureMemoryReady(folder) {
        if (!(await this.extension.ensureWorkspaceTrust())) {
            return {ok: false, reason: "trust"};
        }
        const snapshot = await this.extension.memoryController.ensureSnapshot(folder);
        if (!snapshot.connected) {
            const choice = await vscode.window.showInformationMessage(
                "Connect CodeClone to search Engineering Memory.",
                "Verify Local Server",
                "Analyze Workspace"
            );
            if (choice === "Verify Local Server") {
                await this.extension.connectMcp();
            } else if (choice === "Analyze Workspace") {
                await this.extension.analyzeWorkspace();
            }
            return {ok: false, reason: "disconnected"};
        }
        if (!snapshot.memorySupported) {
            await vscode.window.showWarningMessage(
                "Engineering Memory search requires CodeClone 2.1.0a1 or newer with query_engineering_memory."
            );
            return {ok: false, reason: "unsupported"};
        }
        await this.extension.ensureConnected(folder);
        return {ok: true};
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {string} [initialQuery]
     */
    async promptSearchQuery(folder, initialQuery = "") {
        return vscode.window.showInputBox({
            title: "Search Engineering Memory",
            prompt: "Keyword search (FTS; optional semantic re-rank when enabled in settings)",
            placeHolder: "baseline trust, blast radius, MCP scope…",
            value: initialQuery,
            validateInput: (value) => sanitizeSearchQuery(value),
        });
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {string} query
     * @param {object} [optionsOverride]
     */
    async querySearch(folder, query, optionsOverride = {}) {
        const config = vscode.workspace.getConfiguration("codeclone.memory", folder.uri);
        const options = {...readMemorySearchSettings(config), ...optionsOverride};
        const root = folder.uri.fsPath;
        const response = await this.extension.client.callTool(
            "query_engineering_memory",
            buildSearchToolArgs(root, query, options)
        );
        return {response, options, query};
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {string} relPath
     * @param {object} [optionsOverride]
     */
    async queryForPath(folder, relPath, optionsOverride = {}) {
        const config = vscode.workspace.getConfiguration("codeclone.memory", folder.uri);
        const options = {...readMemorySearchSettings(config), ...optionsOverride};
        const root = folder.uri.fsPath;
        const response = await this.extension.client.callTool(
            "query_engineering_memory",
            buildForPathToolArgs(root, relPath, options)
        );
        return {response, options, relPath};
    }

    /**
     * @param {object[]} records
     * @param {string} title
     */
    async pickRecord(records, title) {
        if (records.length === 0) {
            await vscode.window.showInformationMessage("No engineering memory records matched.");
            return null;
        }
        const items = records.map((record, index) => recordToQuickPickItem(record, index));
        const picked = await vscode.window.showQuickPick(items, {
            title,
            placeHolder: "Open a record or press Escape to dismiss",
            matchOnDescription: true,
            matchOnDetail: true,
        });
        return picked ? picked.record : null;
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {object} record
     */
    async openRecord(folder, record) {
        await this.extension.memoryController.openRecordDetail(folder, {record});
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {string} recordId
     */
    async openRecordById(folder, recordId) {
        if (!isValidMemoryRecordId(recordId)) {
            throw new Error("Invalid memory record id.");
        }
        const record = await this.extension.memoryController.fetchRecordById(
            folder,
            recordId
        );
        await this.openRecord(folder, record);
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     * @param {string} query
     * @param {object} result
     */
    showSearchPanel(folder, query, result) {
        const {renderMemorySearchHtml} = require("./memorySearchRenderer");
        const nonce = require("node:crypto").randomBytes(16).toString("hex");
        const title =
            query.length > 48 ? `Memory Search: ${query.slice(0, 45)}…` : `Memory Search: ${query}`;
        const folderKey = this.sessionKey(folder);
        if (this.activePanel) {
            this.activePanel.title = title;
            this.activePanel.webview.html = renderMemorySearchHtml({
                query,
                result,
                workspaceName: folder.name,
                nonce,
            });
            this.activeSession = {
                folderKey,
                query,
                result,
                folder,
                relPath: result.relPath || this.activeSession?.relPath || null,
            };
            this.activePanel.reveal(vscode.ViewColumn.Beside);
            return;
        }
        const panel = vscode.window.createWebviewPanel(
            "codeclone.memorySearch",
            title,
            vscode.ViewColumn.Beside,
            {
                enableScripts: false,
                enableForms: false,
                enableCommandUris: ["codeclone.openMemoryRecordById"],
                localResourceRoots: [],
                retainContextWhenHidden: true,
            }
        );
        panel.iconPath = new vscode.ThemeIcon("search");
        panel.webview.html = renderMemorySearchHtml({
            query,
            result,
            workspaceName: folder.name,
            nonce,
        });
        panel.onDidDispose(() => {
            if (this.activePanel === panel) {
                this.activePanel = null;
                this.activeSession = null;
            }
        });
        this.activePanel = panel;
        this.activeSession = {
            folderKey,
            query,
            result,
            folder,
            relPath: result.relPath || null,
        };
    }

    async refreshActivePanel() {
        const session = this.activeSession;
        if (!session?.folder || !session.query) {
            await vscode.window.showInformationMessage(
                "Open a memory search panel first (Open Memory Search Panel)."
            );
            return;
        }
        const {folder, query} = session;
        const mode = String(safeObject(safeObject(session.result).response).mode || "search");
        try {
            await vscode.window.withProgress(
                {
                    location: vscode.ProgressLocation.Window,
                    title: "Refreshing engineering memory search",
                },
                async () => {
                    if (mode === "for_path" && session.relPath) {
                        const next = await this.queryForPath(folder, session.relPath);
                        this.showSearchPanel(folder, query, next);
                    } else {
                        const next = await this.querySearch(folder, query);
                        this.showSearchPanel(folder, query, next);
                    }
                }
            );
        } catch (error) {
            this.extension.handleError(error, "Could not refresh memory search.");
        }
    }

    /**
     * @param {import("vscode").WorkspaceFolder} folder
     */
    async configureSearchFilters(folder) {
        const config = vscode.workspace.getConfiguration("codeclone.memory", folder.uri);
        const current = readMemorySearchSettings(config);
        const semanticPick = await vscode.window.showQuickPick(
            [
                {label: "Semantic recall on", value: true},
                {label: "FTS only (semantic off)", value: false},
            ],
            {
                title: "Memory search — semantic",
                placeHolder: formatSemanticStatusLine({}),
            }
        );
        if (!semanticPick) {
            return null;
        }
        const draftsPick = await vscode.window.showQuickPick(
            [
                {label: "Hide drafts", value: false},
                {label: "Include drafts", value: true},
            ],
            {title: "Memory search — drafts"}
        );
        if (!draftsPick) {
            return null;
        }
        const stalePick = await vscode.window.showQuickPick(
            [
                {label: "Hide stale", value: false},
                {label: "Include stale", value: true},
            ],
            {title: "Memory search — stale"}
        );
        if (!stalePick) {
            return null;
        }
        const maxPick = await vscode.window.showQuickPick(
            [
                {label: "10 results", value: 10},
                {label: "20 results", value: 20},
                {label: "50 results", value: 50},
            ],
            {title: "Memory search — limit", placeHolder: `Current: ${current.maxResults}`}
        );
        if (!maxPick) {
            return null;
        }
        const target = vscode.ConfigurationTarget.WorkspaceFolder;
        await config.update("searchSemantic", semanticPick.value, target, folder.uri);
        await config.update("searchIncludeDrafts", draftsPick.value, target, folder.uri);
        await config.update("searchIncludeStale", stalePick.value, target, folder.uri);
        await config.update("searchMaxResults", maxPick.value, target, folder.uri);
        return readMemorySearchSettings(config);
    }

    /**
     * @param {object} result
     */
    extractRecords(result) {
        const payload = safeObject(safeObject(result.response).payload);
        return safeArray(payload.records);
    }
}

module.exports = {
    MEMORY_SEARCH_MAX_QUERY,
    MEMORY_RECORD_ID_PATTERN,
    MemorySearchController,
    sanitizeSearchQuery,
    isValidMemoryRecordId,
    normalizeMemorySearchPath,
    activeEditorMemoryPath,
    readMemorySearchSettings,
    buildSearchToolArgs,
    buildForPathToolArgs,
    formatSemanticStatusLine,
    recordToQuickPickItem,
    memoryRecordCommandUri,
};
