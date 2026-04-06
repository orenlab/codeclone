"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");
/** @type {any} */
const vscode = require("vscode");

const {
    ANALYSIS_PROFILE_OPTIONS,
    HELP_TOPICS,
    HOTSPOT_GROUPS,
    HOTSPOT_FOCUS_MODES,
    HOTSPOT_GROUPS_BY_MODE,
    REVIEW_DECORATION_THEMES,
    WORKSPACE_STATE_HOTSPOT_FOCUS_MODE,
    WORKSPACE_STATE_LAST_HELP_TOPIC,
} = require("./constants");
const {
    capitalize,
    compactDecimal,
    decimal,
    emptyReviewArtifacts,
    findingIcon,
    firstNormalizedLocation,
    focusModeSpec,
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
    normalizeRelativePath,
    number,
    reviewTargetKey,
    safeArray,
    safeObject,
    sameLaunchSpec,
    treeAccessibilityInformation,
    workspaceRelativePath,
} = require("./formatters");
const {CodeCloneMcpClient, MCPClientError} = require("./mcpClient");
const {
    markdownBulletList,
    renderFindingMarkdown,
    renderOverloadedModuleMarkdown,
    renderHelpMarkdown,
    renderRemediationMarkdown,
    renderRestrictedModeMarkdown,
    renderSetupMarkdown,
    renderTriageMarkdown,
} = require("./renderers");
const {
    HotspotsTreeProvider,
    OverviewTreeProvider,
    ReviewCodeLensProvider,
    ReviewFileDecorationProvider,
    SessionTreeProvider,
    WorkspaceState,
} = require("./providers");
const {
    captureWorkspaceGitSnapshot,
    looksLikeCodeCloneRepo,
    pathExists,
    readFileHead,
    sameGitSnapshot,
} = require("./runtime");
const {
    ANALYSIS_PROFILE_CUSTOM,
    ANALYSIS_PROFILE_DEFAULTS,
    MINIMUM_SUPPORTED_CODECLONE_VERSION,
    PREVIEW_INSTALL_COMMAND,
    STALE_REASON_EDITOR,
    STALE_REASON_WORKSPACE,
    isMinimumSupportedCodeCloneVersion,
    resolveAnalysisSettings,
    sameAnalysisSettings,
    locationsNeedDetailHydration,
    normalizedLaunchSpec,
    parseUtcTimestamp,
    revealLineSpan,
    resolveWorkspacePath,
    signedInteger,
    staleMessage,
    unsupportedVersionMessage,
    workspaceLocalLauncherCandidates,
} = require("./support");

class CodeCloneController {
    constructor(context) {
        this.context = context;
        this.disposed = false;
        this.outputChannel = vscode.window.createOutputChannel("CodeClone");
        this.client = new CodeCloneMcpClient(this.outputChannel);
        this.states = new Map();
        this.hotspotFocusMode = this.loadHotspotFocusMode();
        const storedHelpTopic = this.context.workspaceState.get(
            WORKSPACE_STATE_LAST_HELP_TOPIC,
            HELP_TOPICS[0]
        );
        this.lastHelpTopic = HELP_TOPICS.includes(storedHelpTopic)
            ? storedHelpTopic
            : HELP_TOPICS[0];
        this.activeReviewTarget = null;
        this.fileDecorations = new Map();
        this.revealDecoration = vscode.window.createTextEditorDecorationType({
            isWholeLine: true,
            borderWidth: "1px",
            borderStyle: "solid",
            borderColor: new vscode.ThemeColor("editor.wordHighlightStrongBorder"),
            backgroundColor: new vscode.ThemeColor(
                "editor.wordHighlightStrongBackground"
            ),
        });
        this.revealDecorationTimeout = null;
        this.connectionInfo = /** @type {any} */ ({
            connected: false,
            serverInfo: null,
            toolCount: 0,
            launchSpec: null,
        });
        this.statusBar = vscode.window.createStatusBarItem(
            "codeclone.status",
            vscode.StatusBarAlignment.Left,
            10
        );
        this.statusBar.name = "CodeClone";
        this.statusBar.command = "codeclone.openOverview";
        this.overviewProvider = new OverviewTreeProvider(this);
        this.hotspotsProvider = new HotspotsTreeProvider(this);
        this.sessionProvider = new SessionTreeProvider(this);
        this.reviewCodeLensProvider = new ReviewCodeLensProvider(this);
        this.reviewFileDecorationProvider = new ReviewFileDecorationProvider(this);
        this.overviewView = vscode.window.createTreeView("codeclone.overview", {
            treeDataProvider: this.overviewProvider,
            showCollapseAll: false,
        });
        this.hotspotsView = vscode.window.createTreeView("codeclone.hotspots", {
            treeDataProvider: this.hotspotsProvider,
            showCollapseAll: true,
        });
        this.sessionView = vscode.window.createTreeView("codeclone.session", {
            treeDataProvider: this.sessionProvider,
            showCollapseAll: false,
        });
        this.onClientState = (state) => {
            if (this.disposed) {
                return;
            }
            this.connectionInfo.connected = Boolean(state.connected);
            this.connectionInfo.serverInfo = state.connected
                ? state.serverInfo || null
                : null;
            this.connectionInfo.toolCount = state.connected
                ? safeArray(state.toolNames).length
                : 0;
            this.connectionInfo.launchSpec = state.connected
                ? state.launchSpec || this.connectionInfo.launchSpec
                : null;
            this.updateContextKeys();
            this.updateStatusBar();
            this.refreshAllViews();
        };
        this.onClientExit = async () => {
            if (this.disposed) {
                return;
            }
            await vscode.window.showWarningMessage(
                "The local CodeClone server disconnected. Run Analyze Workspace or Review Changes to reconnect."
            );
        };
        this.client.on("state", this.onClientState);
        this.client.on("exit", this.onClientExit);
        context.subscriptions.push(
            this.outputChannel,
            this.statusBar,
            this.revealDecoration,
            this.overviewProvider,
            this.hotspotsProvider,
            this.sessionProvider,
            this.reviewCodeLensProvider,
            this.reviewFileDecorationProvider,
            this.overviewView,
            this.hotspotsView,
            this.sessionView,
            vscode.languages.registerCodeLensProvider(
                {scheme: "file"},
                this.reviewCodeLensProvider
            ),
            vscode.window.registerFileDecorationProvider(
                this.reviewFileDecorationProvider
            ),
            vscode.workspace.onDidChangeTextDocument((event) =>
                this.handleTextDocumentChanged(event)
            ),
            vscode.workspace.onDidSaveTextDocument((document) =>
                this.handleTextDocumentSaved(document)
            ),
            vscode.window.onDidChangeActiveTextEditor(() =>
                this.handleActiveEditorChanged()
            ),
            vscode.window.onDidChangeWindowState((state) =>
                this.handleWindowStateChanged(state)
            ),
            vscode.workspace.onDidChangeWorkspaceFolders((event) =>
                this.handleWorkspaceFoldersChanged(event)
            ),
            vscode.workspace.onDidGrantWorkspaceTrust(() =>
                this.handleWorkspaceTrustGranted()
            ),
            {
                dispose: () => {
                    void this.dispose();
                },
            }
        );
        this.registerCommands();
        this.updateContextKeys();
        this.updateStatusBar();
        this.updateViewChrome();
    }

    async dispose() {
        if (this.disposed) {
            return;
        }
        this.disposed = true;
        if (this.revealDecorationTimeout) {
            clearTimeout(this.revealDecorationTimeout);
            this.revealDecorationTimeout = null;
        }
        this.client.off("state", this.onClientState);
        this.client.off("exit", this.onClientExit);
        this.activeReviewTarget = null;
        this.fileDecorations.clear();
        this.states.clear();
        await this.client.dispose({emitState: false});
    }

    registerCommands() {
        const subscriptions = [
            vscode.commands.registerCommand("codeclone.manageWorkspaceTrust", () =>
                this.manageWorkspaceTrust()
            ),
            vscode.commands.registerCommand("codeclone.connectMcp", () =>
                this.connectMcp()
            ),
            vscode.commands.registerCommand("codeclone.analyzeWorkspace", (arg) =>
                this.analyzeWorkspace(arg)
            ),
            vscode.commands.registerCommand("codeclone.analyzeChangedFiles", (arg) =>
                this.analyzeChangedFiles(arg)
            ),
            vscode.commands.registerCommand("codeclone.setAnalysisProfile", (arg) =>
                this.setAnalysisProfile(arg)
            ),
            vscode.commands.registerCommand("codeclone.refreshCurrentRun", () =>
                this.refreshCurrentRun()
            ),
            vscode.commands.registerCommand("codeclone.openProductionTriage", () =>
                this.openProductionTriage()
            ),
            vscode.commands.registerCommand("codeclone.reviewPriorityQueue", () =>
                this.reviewPriorityQueue()
            ),
            vscode.commands.registerCommand("codeclone.focusHotspots", () =>
                this.focusHotspots()
            ),
            vscode.commands.registerCommand("codeclone.nextReviewItem", () =>
                this.moveReviewCursor(1)
            ),
            vscode.commands.registerCommand("codeclone.previousReviewItem", () =>
                this.moveReviewCursor(-1)
            ),
            vscode.commands.registerCommand("codeclone.setHotspotFocusMode", () =>
                this.setHotspotFocusMode()
            ),
            vscode.commands.registerCommand("codeclone.reviewFinding", (node) =>
                this.reviewFinding(node)
            ),
            vscode.commands.registerCommand("codeclone.openFinding", (node) =>
                this.openFinding(node)
            ),
            vscode.commands.registerCommand("codeclone.peekFindingLocations", (node) =>
                this.peekFindingLocations(node)
            ),
            vscode.commands.registerCommand("codeclone.showRemediation", (node) =>
                this.showRemediation(node)
            ),
            vscode.commands.registerCommand("codeclone.markFindingReviewed", (node) =>
                this.markFindingReviewed(node)
            ),
            vscode.commands.registerCommand("codeclone.copyFindingId", (node) =>
                this.copyFindingId(node)
            ),
            vscode.commands.registerCommand("codeclone.copyFindingContext", (node) =>
                this.copyFindingContext(node)
            ),
            vscode.commands.registerCommand("codeclone.copyRefactorBrief", (node) =>
                this.copyRefactorBrief(node)
            ),
            vscode.commands.registerCommand("codeclone.openInHtmlReport", (node) =>
                this.openInHtmlReport(node)
            ),
            vscode.commands.registerCommand("codeclone.revealFindingSource", (node) =>
                this.revealFindingSource(node)
            ),
            vscode.commands.registerCommand("codeclone.showHelpTopic", (arg) =>
                this.showHelpTopic(arg)
            ),
            vscode.commands.registerCommand("codeclone.openSetupHelp", () =>
                this.openSetupHelp()
            ),
            vscode.commands.registerCommand("codeclone.openOverview", () =>
                this.openOverview()
            ),
            vscode.commands.registerCommand("codeclone.clearSessionState", () =>
                this.clearSessionState()
            ),
            vscode.commands.registerCommand("codeclone.openOverloadedModule", (node) =>
                this.openOverloadedModule(node)
            ),
            vscode.commands.registerCommand("codeclone.copyOverloadedModuleBrief", (node) =>
                this.copyOverloadedModuleBrief(node)
            ),
            vscode.commands.registerCommand("codeclone.reviewOverloadedModule", (node) =>
                this.reviewOverloadedModule(node)
            ),
        ];
        this.context.subscriptions.push(...subscriptions);
    }

    getWorkspaceState(folder) {
        const key = folder.uri.toString();
        if (!this.states.has(key)) {
            this.states.set(key, new WorkspaceState(folder));
        }
        return this.states.get(key);
    }

    getPrimaryState() {
        const activeFolder = this.getPreferredFolder();
        if (activeFolder) {
            const activeState = this.states.get(activeFolder.uri.toString()) || null;
            if (activeState) {
                return activeState;
            }
        }
        const analyzed = Array.from(this.states.values()).find(
            (state) => state.latestSummary !== null
        );
        return analyzed || null;
    }

    getPreferredFolder() {
        const activeEditor = vscode.window.activeTextEditor;
        if (activeEditor) {
            const folder = vscode.workspace.getWorkspaceFolder(activeEditor.document.uri);
            if (folder) {
                return folder;
            }
        }
        return vscode.workspace.workspaceFolders?.[0] || null;
    }

    async ensureWorkspaceTrust() {
        if (vscode.workspace.isTrusted) {
            return true;
        }
        const choice = await vscode.window.showWarningMessage(
            "CodeClone requires a trusted workspace before it starts local analysis or a local MCP server.",
            "Manage Workspace Trust"
        );
        if (choice === "Manage Workspace Trust") {
            await vscode.commands.executeCommand("workbench.trust.manage");
        }
        return false;
    }

    loadHotspotFocusMode() {
        const stored = this.context.workspaceState.get(
            WORKSPACE_STATE_HOTSPOT_FOCUS_MODE,
            "recommended"
        );
        const allowed = new Set(HOTSPOT_FOCUS_MODES.map((entry) => entry.id));
        return allowed.has(stored) ? stored : "recommended";
    }

    async persistHotspotFocusMode() {
        await this.context.workspaceState.update(
            WORKSPACE_STATE_HOTSPOT_FOCUS_MODE,
            this.hotspotFocusMode
        );
    }

    async persistLastHelpTopic(topic) {
        this.lastHelpTopic = HELP_TOPICS.includes(topic) ? topic : HELP_TOPICS[0];
        await this.context.workspaceState.update(
            WORKSPACE_STATE_LAST_HELP_TOPIC,
            this.lastHelpTopic
        );
    }

    async manageWorkspaceTrust() {
        await vscode.commands.executeCommand("workbench.trust.manage");
    }

    handleWorkspaceTrustGranted() {
        this.updateContextKeys();
        this.updateStatusBar();
        this.refreshAllViews();
        void vscode.window.showInformationMessage(
            "Workspace trust granted. CodeClone analysis is now available."
        );
    }

    async pickWorkspaceFolder(placeHolder) {
        if (!(await this.ensureWorkspaceTrust())) {
            return null;
        }
        const folders = vscode.workspace.workspaceFolders || [];
        if (folders.length === 0) {
            await vscode.window.showErrorMessage(
                "Open a workspace folder before using CodeClone."
            );
            return null;
        }
        if (folders.length === 1) {
            return folders[0];
        }
        const picked = await vscode.window.showQuickPick(
            folders.map((folder) => ({
                label: folder.name,
                description: folder.uri.fsPath,
                folder,
            })),
            {
                title: "Select Workspace",
                placeHolder,
            }
        );
        return picked ? picked.folder : null;
    }

    async resolveFolderFromArg(arg, prompt) {
        if (arg && arg.workspaceKey && this.states.has(arg.workspaceKey)) {
            return this.states.get(arg.workspaceKey).folder;
        }
        return this.pickWorkspaceFolder(prompt);
    }

    async resolvePreferredFolderFromArg(arg, prompt) {
        if (arg && arg.workspaceKey && this.states.has(arg.workspaceKey)) {
            return this.states.get(arg.workspaceKey).folder;
        }
        const preferred = this.getPreferredFolder();
        if (preferred) {
            return preferred;
        }
        const primaryState = this.getPrimaryState();
        if (primaryState) {
            return primaryState.folder;
        }
        return this.pickWorkspaceFolder(prompt);
    }

    configurationTarget() {
        return (vscode.workspace.workspaceFolders || []).length > 1
            ? vscode.ConfigurationTarget.WorkspaceFolder
            : vscode.ConfigurationTarget.Workspace;
    }

    configuredAnalysisSettings(folder) {
        const config = vscode.workspace.getConfiguration("codeclone", folder.uri);
        return resolveAnalysisSettings({
            profile: config.get("analysis.profile", "defaults"),
            minLoc: config.get("analysis.minLoc", 10),
            minStmt: config.get("analysis.minStmt", 6),
            blockMinLoc: config.get("analysis.blockMinLoc", 20),
            blockMinStmt: config.get("analysis.blockMinStmt", 8),
            segmentMinLoc: config.get("analysis.segmentMinLoc", 20),
            segmentMinStmt: config.get("analysis.segmentMinStmt", 10),
        });
    }

    stateForDocument(document) {
        if (!document || !document.uri) {
            return null;
        }
        const folder = vscode.workspace.getWorkspaceFolder(document.uri);
        if (!folder) {
            return null;
        }
        return this.states.get(folder.uri.toString()) || null;
    }

    handleTextDocumentChanged(event) {
        const state = this.stateForDocument(event.document);
        if (!state || !state.latestSummary) {
            return;
        }
        state.stale = true;
        state.staleReason = STALE_REASON_EDITOR;
        this.updateContextKeys();
        this.updateStatusBar();
        this.refreshAllViews();
    }

    async handleTextDocumentSaved(document) {
        const state = this.stateForDocument(document);
        if (!state || !state.latestSummary) {
            return;
        }
        await this.refreshStaleState(state);
    }

    async handleActiveEditorChanged() {
        this.reviewCodeLensProvider.refresh();
        this.updateContextKeys();
        const state = this.getPrimaryState();
        if (!state || !state.latestSummary) {
            return;
        }
        await this.refreshStaleState(state);
    }

    async handleWindowStateChanged(windowState) {
        if (!windowState.focused) {
            return;
        }
        const state = this.getPrimaryState();
        if (!state || !state.latestSummary) {
            return;
        }
        await this.refreshStaleState(state);
    }

    handleWorkspaceFoldersChanged(event) {
        if (this.disposed || !event.removed.length) {
            return;
        }
        const removedKeys = new Set(
            event.removed.map((folder) => folder.uri.toString())
        );
        let changed = false;
        for (const key of removedKeys) {
            changed = this.states.delete(key) || changed;
        }
        if (!changed) {
            return;
        }
        if (
            this.activeReviewTarget &&
            removedKeys.has(this.activeReviewTarget.workspaceKey)
        ) {
            this.activeReviewTarget = null;
        }
        this.rebuildFileDecorations();
        this.updateContextKeys();
        this.updateStatusBar();
        this.refreshAllViews();
    }

    async resolveLaunchSpec(folder) {
        const config = vscode.workspace.getConfiguration("codeclone", folder.uri);
        const configuredCommand = config.get("mcp.command", "auto");
        const configuredArgs = config.get("mcp.args", []);
        if (configuredCommand && configuredCommand !== "auto") {
            return normalizedLaunchSpec({
                command: configuredCommand,
                args: Array.isArray(configuredArgs) ? configuredArgs : [],
                cwd: folder.uri.fsPath,
                source: "configured",
            });
        }
        const candidates = workspaceLocalLauncherCandidates(folder.uri.fsPath);
        const candidateChecks = await Promise.all(
            candidates.map(async (candidate) => ({
                candidate,
                exists: await pathExists(candidate),
            }))
        );
        const localLauncher = candidateChecks.find((entry) => entry.exists)?.candidate;
        if (localLauncher) {
            return normalizedLaunchSpec({
                command: localLauncher,
                args: Array.isArray(configuredArgs) ? configuredArgs : [],
                cwd: folder.uri.fsPath,
                source: "workspaceLocal",
            });
        }
        const primary = /** @type {any} */ (normalizedLaunchSpec({
            command: "codeclone-mcp",
            args: Array.isArray(configuredArgs) ? configuredArgs : [],
            cwd: folder.uri.fsPath,
            source: "path",
        }));
        primary.fallback = (await looksLikeCodeCloneRepo(folder.uri.fsPath))
            ? normalizedLaunchSpec({
                command: "uv",
                args: ["run", "codeclone-mcp"],
                cwd: folder.uri.fsPath,
                source: "uvFallback",
            })
            : null;
        return primary;
    }

    async ensureConnected(folder) {
        const launchSpec = await this.resolveLaunchSpec(folder);
        if (this.client.isConnected() && this.connectionInfo.launchSpec) {
            const activeLaunchSpec = this.connectionInfo.launchSpec;
            if (
                sameLaunchSpec(activeLaunchSpec, launchSpec) ||
                sameLaunchSpec(activeLaunchSpec, launchSpec.fallback)
            ) {
                const snapshot = this.client.getConnectionSnapshot();
                this.connectionInfo.connected = snapshot.connected;
                this.connectionInfo.serverInfo = snapshot.serverInfo;
                this.connectionInfo.toolCount = snapshot.toolNames.length;
                this.connectionInfo.launchSpec = snapshot.launchSpec;
                return snapshot;
            }
        }
        let effectiveLaunchSpec = launchSpec;
        let connection;
        try {
            connection = await this.client.connect(launchSpec);
        } catch (error) {
            if (launchSpec.fallback) {
                this.outputChannel.appendLine(
                    "[codeclone] primary MCP launch failed, trying fallback launcher."
                );
                effectiveLaunchSpec = launchSpec.fallback;
                connection = await this.client.connect(effectiveLaunchSpec);
            } else {
                throw error;
            }
        }
        this.connectionInfo.connected = true;
        this.connectionInfo.serverInfo = connection.serverInfo || null;
        this.connectionInfo.toolCount = connection.toolNames.length;
        this.connectionInfo.launchSpec = effectiveLaunchSpec;
        if (!isMinimumSupportedCodeCloneVersion(this.connectionInfo.serverInfo?.version)) {
            const reportedVersion = this.connectionInfo.serverInfo?.version || "unknown";
            await this.client.dispose({emitState: false});
            this.connectionInfo.connected = false;
            this.connectionInfo.serverInfo = null;
            this.connectionInfo.toolCount = 0;
            this.connectionInfo.launchSpec = null;
            this.updateContextKeys();
            this.updateStatusBar();
            throw new MCPClientError(
                unsupportedVersionMessage(
                    reportedVersion,
                    MINIMUM_SUPPORTED_CODECLONE_VERSION,
                    effectiveLaunchSpec
                )
            );
        }
        this.updateContextKeys();
        this.updateStatusBar();
        return connection;
    }

    async connectMcp() {
        const folder = await this.pickWorkspaceFolder("Select a workspace for CodeClone MCP");
        if (!folder) {
            return;
        }
        try {
            await vscode.window.withProgress(
                {
                    location: vscode.ProgressLocation.Notification,
                    title: "Verifying local CodeClone server",
                },
                async () => {
                    await this.ensureConnected(folder);
                }
            );
            await vscode.window.showInformationMessage(
                `Local CodeClone server is ready (${this.connectionInfo.toolCount} tools).`
            );
            this.refreshAllViews();
        } catch (error) {
            this.handleError(error, "Could not connect to CodeClone MCP.");
        }
    }

    async refreshStaleState(state) {
        if (this.disposed || !state || !state.latestSummary) {
            return;
        }
        const now = Date.now();
        if (now - Number(state.lastStaleCheckAt || 0) < 750) {
            return;
        }
        state.lastStaleCheckAt = now;
        const hasDirtyEditors = vscode.workspace.textDocuments.some((document) => {
            if (!document.isDirty) {
                return false;
            }
            const folder = vscode.workspace.getWorkspaceFolder(document.uri);
            return Boolean(folder && folder.uri.toString() === state.folder.uri.toString());
        });
        if (hasDirtyEditors) {
            state.stale = true;
            state.staleReason = STALE_REASON_EDITOR;
            this.updateContextKeys();
            this.updateStatusBar();
            this.refreshAllViews();
            return;
        }
        const snapshot = await captureWorkspaceGitSnapshot(state.folder);
        if (this.disposed) {
            return;
        }
        if (!sameGitSnapshot(snapshot, state.gitSnapshot)) {
            state.stale = true;
            state.staleReason = STALE_REASON_WORKSPACE;
        } else {
            state.stale = false;
            state.staleReason = null;
        }
        this.updateContextKeys();
        this.updateStatusBar();
        this.refreshAllViews();
    }

    async refreshReviewArtifacts(state) {
        if (this.disposed || !state || !state.currentRunId) {
            if (state) {
                state.reviewArtifacts = emptyReviewArtifacts();
                state.groupCache.clear();
            }
            this.rebuildFileDecorations();
            return;
        }
        const runId = state.currentRunId;
        const diffRef = vscode.workspace
            .getConfiguration("codeclone", state.folder.uri)
            .get("analysis.changedDiffRef", "HEAD");
        const [
            newRegressionsResponse,
            productionHotspotsResponse,
            changedFilesResponse,
            overloadedModulesResponse,
        ] = await Promise.all([
            this.client.callTool("list_findings", {
                run_id: runId,
                novelty: "new",
                detail_level: "summary",
                sort_by: "priority",
                limit: 200,
                exclude_reviewed: true,
            }),
            this.client.callTool("list_hotspots", {
                run_id: runId,
                kind: "production_hotspots",
                detail_level: "summary",
                limit: 100,
                exclude_reviewed: true,
            }),
            state.changedSummary
                ? this.client.callTool("list_findings", {
                    run_id: runId,
                    git_diff_ref: diffRef,
                    novelty: "new",
                    detail_level: "summary",
                    sort_by: "priority",
                    limit: 200,
                    exclude_reviewed: true,
                })
                : Promise.resolve({items: []}),
            this.client.callTool("get_report_section", {
                run_id: runId,
                section: "metrics_detail",
                family: "overloaded_modules",
                limit: 25,
            }),
        ]);
        if (this.disposed) {
            return;
        }
        state.reviewArtifacts = {
            newRegressions: safeArray(newRegressionsResponse.items),
            productionHotspots: safeArray(productionHotspotsResponse.items),
            changedFiles: safeArray(changedFilesResponse.items),
            overloadedModules: safeArray(overloadedModulesResponse.items),
        };
        state.groupCache.clear();
        this.rebuildFileDecorations();
    }

    rebuildFileDecorations() {
        if (this.disposed) {
            return;
        }
        this.fileDecorations.clear();
        for (const state of this.states.values()) {
            if (!state.latestSummary) {
                continue;
            }
            const artifacts = safeObject(state.reviewArtifacts);
            this.addFileDecorationRows(
                state,
                safeArray(artifacts.newRegressions),
                "new"
            );
            this.addFileDecorationRows(
                state,
                safeArray(artifacts.productionHotspots),
                "production"
            );
            this.addFileDecorationRows(
                state,
                safeArray(artifacts.changedFiles),
                "changed"
            );
        }
        this.reviewFileDecorationProvider.refresh(undefined);
    }

    addFileDecorationRows(state, rows, kind) {
        for (const row of rows) {
            for (const location of normalizeFindingLocations(state.folder, row.locations)) {
                const key = vscode.Uri.file(location.absolutePath).toString();
                const entry =
                    this.fileDecorations.get(key) || {
                        kinds: new Set(),
                        findingIds: new Set(),
                    };
                entry.kinds.add(kind);
                if (row.id) {
                    entry.findingIds.add(String(row.id));
                }
                this.fileDecorations.set(key, entry);
            }
        }
    }

    provideFileDecoration(uri) {
        const entry = this.fileDecorations.get(uri.toString());
        if (!entry) {
            return undefined;
        }
        const kinds = entry.kinds;
        const theme = kinds.has("new")
            ? REVIEW_DECORATION_THEMES.new
            : kinds.has("production")
                ? REVIEW_DECORATION_THEMES.production
                : REVIEW_DECORATION_THEMES.changed;
        const labels = [];
        if (kinds.has("new")) {
            labels.push("new regressions");
        }
        if (kinds.has("production")) {
            labels.push("production hotspots");
        }
        if (kinds.has("changed")) {
            labels.push("changed-files review items");
        }
        return {
            badge: theme.badge,
            color: new vscode.ThemeColor(theme.color),
            tooltip: `CodeClone: ${labels.join(" · ")}`,
            propagate: kinds.has("new") || kinds.has("production"),
        };
    }

    async analyzeWorkspace(arg) {
        const folder = await this.resolveFolderFromArg(
            arg,
            "Select a workspace to analyze with CodeClone"
        );
        if (!folder) {
            return;
        }
        await this.runAnalysis(folder, false);
    }

    async analyzeChangedFiles(arg) {
        const folder = await this.resolveFolderFromArg(
            arg,
            "Select a workspace for changed-files analysis"
        );
        if (!folder) {
            return;
        }
        await this.runAnalysis(folder, true);
    }

    async setAnalysisProfile(arg) {
        const folder = await this.resolvePreferredFolderFromArg(
            arg,
            "Select a workspace for CodeClone analysis settings"
        );
        if (!folder) {
            return;
        }
        const currentSettings = this.configuredAnalysisSettings(folder);
        const state = this.getWorkspaceState(folder);
        const picked = await vscode.window.showQuickPick(
            ANALYSIS_PROFILE_OPTIONS.map((entry) => ({
                label: entry.label,
                description:
                    entry.id === currentSettings.profileId
                        ? "Selected for next run"
                        : entry.description,
                detail: entry.detail,
                profileId: entry.id,
            })),
            {
                title: "Set Analysis Depth",
                placeHolder:
                    "Select how sensitive CodeClone should be on the next analysis run",
                matchOnDetail: true,
            }
        );
        if (!picked) {
            return;
        }

        const config = vscode.workspace.getConfiguration("codeclone", folder.uri);
        await config.update(
            "analysis.profile",
            picked.profileId,
            this.configurationTarget()
        );

        const nextSettings = this.configuredAnalysisSettings(folder);
        this.refreshAllViews();
        this.updateStatusBar();
        this.updateViewChrome();

        const rerunActions =
            picked.profileId === ANALYSIS_PROFILE_CUSTOM
                ? state && state.latestSummary
                    ? state.lastScope === "changed"
                        ? ["Open Settings", "Review Changes", "Analyze Workspace", "Later"]
                        : ["Open Settings", "Analyze Workspace", "Review Changes", "Later"]
                    : ["Open Settings", "Later"]
                : state && state.latestSummary
                    ? state.lastScope === "changed"
                        ? ["Review Changes", "Analyze Workspace", "Later"]
                        : ["Analyze Workspace", "Review Changes", "Later"]
                    : ["Analyze Workspace", "Later"];
        const message = `CodeClone analysis depth set to ${nextSettings.label}.`;
        const choice = await vscode.window.showInformationMessage(
            picked.profileId === ANALYSIS_PROFILE_CUSTOM
                ? `${message} Update the workspace thresholds if you want custom values before the next run.`
                : `${message} Re-run analysis when you want the new profile to take effect.`,
            ...rerunActions
        );

        if (choice === "Analyze Workspace") {
            await this.runAnalysis(folder, false);
            return;
        }
        if (choice === "Review Changes") {
            await this.runAnalysis(folder, true);
            return;
        }
        if (choice === "Open Settings") {
            await vscode.commands.executeCommand(
                "workbench.action.openSettings",
                "@ext:orenlab.codeclone codeclone.analysis"
            );
        }
    }

    async refreshCurrentRun() {
        const state = this.getPrimaryState();
        if (!state) {
            await this.analyzeWorkspace();
            return;
        }
        await this.runAnalysis(state.folder, state.lastScope === "changed");
    }

    async runAnalysis(folder, changedMode) {
        if (this.disposed) {
            return;
        }
        const state = this.getWorkspaceState(folder);
        const config = vscode.workspace.getConfiguration("codeclone", folder.uri);
        const cachePolicy = config.get("analysis.cachePolicy", "reuse");
        const diffRef = config.get("analysis.changedDiffRef", "HEAD");
        const analysisSettings = this.configuredAnalysisSettings(folder);
        const title = changedMode
            ? `CodeClone: Analyzing changed files in ${folder.name}`
            : `CodeClone: Analyzing ${folder.name}`;
        const profileTitleSuffix =
            analysisSettings.profileId === ANALYSIS_PROFILE_DEFAULTS
                ? ""
                : ` (${analysisSettings.label})`;
        const previousText = this.statusBar.text;
        this.statusBar.text = "$(loading~spin) CodeClone analyzing";
        this.statusBar.show();
        try {
            await vscode.window.withProgress(
                {
                    location: vscode.ProgressLocation.Notification,
                    title: `${title}${profileTitleSuffix}`,
                },
                async () => {
                    await this.ensureConnected(folder);
                    const analysisPayload = changedMode
                        ? await this.client.callTool("analyze_changed_paths", {
                            root: folder.uri.fsPath,
                            git_diff_ref: diffRef,
                            cache_policy: cachePolicy,
                            ...analysisSettings.overrides,
                        })
                        : await this.client.callTool("analyze_repository", {
                            root: folder.uri.fsPath,
                            cache_policy: cachePolicy,
                            ...analysisSettings.overrides,
                        });
                    const runId = String(analysisPayload.run_id);
                    const summary = await this.client.callTool("get_run_summary", {
                        run_id: runId,
                    });
                    const triage = await this.client.callTool("get_production_triage", {
                        run_id: runId,
                        max_hotspots: 5,
                        max_suggestions: 5,
                    });
                    const metrics = await this.client.callTool("get_report_section", {
                        run_id: runId,
                        section: "metrics",
                    });
                    const reviewed = await this.client.callTool("list_reviewed_findings", {
                        run_id: runId,
                    });
                    const gitSnapshot = await captureWorkspaceGitSnapshot(folder);
                    state.currentRunId = runId;
                    state.latestSummary = summary;
                    state.latestTriage = triage;
                    state.metricsSummary = metrics.summary || metrics;
                    state.changedSummary = changedMode ? analysisPayload : null;
                    state.analysisSettings = analysisSettings;
                    state.reviewed = safeArray(reviewed.items);
                    state.lastScope = changedMode ? "changed" : "workspace";
                    state.lastUpdatedAt = new Date();
                    state.gitSnapshot = gitSnapshot;
                    state.stale = false;
                    state.staleReason = null;
                    state.lastStaleCheckAt = Date.now();
                    state.groupCache.clear();
                    await this.refreshReviewArtifacts(state);
                }
            );
            this.clearActiveReviewTarget();
            if (this.disposed) {
                return;
            }
            this.updateContextKeys();
            this.updateStatusBar();
            this.refreshAllViews();
            await this.openOverview();
        } catch (error) {
            if (!this.disposed) {
                this.handleError(error, "CodeClone analysis failed.");
            }
        } finally {
            if (this.disposed) {
                return;
            }
            if (!this.connectionInfo.connected) {
                this.statusBar.text = "CodeClone disconnected";
            } else if (previousText) {
                this.updateStatusBar();
            }
        }
    }

    async openOverview() {
        await vscode.commands.executeCommand("workbench.view.extension.codeclone");
        await vscode.commands.executeCommand("codeclone.overview.focus");
    }

    async focusHotspots() {
        await vscode.commands.executeCommand("workbench.view.extension.codeclone");
        await vscode.commands.executeCommand("codeclone.hotspots.focus");
    }

    async openProductionTriage() {
        const state = this.getPrimaryState();
        if (!state || !state.latestTriage) {
            await vscode.window.showInformationMessage(
                "Start with Analyze Workspace or Review Changes before opening triage."
            );
            return;
        }
        await this.showMarkdownDocument(renderTriageMarkdown(state));
    }

    setActiveReviewTarget(target) {
        this.activeReviewTarget = target || null;
        this.updateContextKeys();
        this.reviewCodeLensProvider.refresh();
    }

    clearActiveReviewTarget() {
        this.setActiveReviewTarget(null);
    }

    activeFindingTarget(node) {
        const candidate = node || this.activeReviewTarget;
        if (
            !candidate ||
            candidate.nodeType === "overloadedModule" ||
            !candidate.findingId
        ) {
            return null;
        }
        return candidate;
    }

    activeOverloadedModuleTarget(node) {
        const candidate = node || this.activeReviewTarget;
        if (
            !candidate ||
            candidate.nodeType !== "overloadedModule" ||
            !safeObject(candidate.item).path
        ) {
            return null;
        }
        return candidate;
    }

    isTargetVisibleInEditor(target, editor = vscode.window.activeTextEditor) {
        if (!target || !editor || !editor.document) {
            return false;
        }
        const fsPath = editor.document.uri.fsPath;
        if (target.nodeType === "overloadedModule") {
            const state = this.states.get(target.workspaceKey);
            if (!state) {
                return false;
            }
            return workspaceRelativePath(state.folder, fsPath) === normalizeRelativePath(target.item.path);
        }
        return safeArray(target.locations).some(
            (location) => location.absolutePath === fsPath
        );
    }

    async resolveFindingNode(node) {
        const activeNode = this.activeFindingTarget(node);
        if (!activeNode || !activeNode.findingId || !activeNode.runId) {
            return null;
        }
        const state = this.states.get(activeNode.workspaceKey);
        if (!state) {
            return null;
        }
        let detailPayload =
            activeNode.detailPayload && typeof activeNode.detailPayload === "object"
                ? activeNode.detailPayload
                : null;
        let locations = detailPayload
            ? normalizeFindingLocations(state.folder, detailPayload.locations)
            : normalizeFindingLocations(state.folder, activeNode.locations);
        if (
            !detailPayload ||
            locations.length === 0 ||
            locationsNeedDetailHydration(activeNode.locations)
        ) {
            await this.ensureConnected(state.folder);
            detailPayload = await this.client.callTool("get_finding", {
                run_id: activeNode.runId,
                finding_id: activeNode.findingId,
                detail_level: "normal",
            });
            const detailLocations = normalizeFindingLocations(
                state.folder,
                detailPayload.locations
            );
            if (detailLocations.length > 0) {
                locations = detailLocations;
            }
        }
        const resolved = {
            ...activeNode,
            nodeType: "finding",
            workspaceKey: state.folder.uri.toString(),
            runId: activeNode.runId,
            findingId: activeNode.findingId,
            locations,
            detailPayload,
            reviewed: Boolean(activeNode.reviewed),
        };
        this.setActiveReviewTarget(resolved);
        return resolved;
    }

    reviewArtifactItems(state, groupId) {
        if (!state) {
            return [];
        }
        const artifacts = safeObject(state.reviewArtifacts);
        switch (groupId) {
            case "newRegressions":
                return safeArray(artifacts.newRegressions);
            case "productionHotspots":
                return safeArray(artifacts.productionHotspots);
            case "changedFiles":
                return safeArray(artifacts.changedFiles);
            case "overloadedModules":
                return safeArray(artifacts.overloadedModules);
            default:
                return [];
        }
    }

    reviewArtifactCount(state, groupId) {
        return this.reviewArtifactItems(state, groupId).length;
    }

    activeHotspotGroupIds(state) {
        const requested =
            /** @type {any} */ (HOTSPOT_GROUPS_BY_MODE)[this.hotspotFocusMode] ||
            HOTSPOT_GROUPS_BY_MODE.recommended;
        if (this.hotspotFocusMode === "all") {
            return requested;
        }
        return requested.filter((groupId) => this.shouldShowGroup(groupId, state));
    }

    baselineDrift(state) {
        if (!state || !state.latestSummary) {
            return {
                cloneTrusted: false,
                metricsTrusted: false,
                newFindings: null,
                newClones: null,
                healthDelta: null,
            };
        }
        const summary = safeObject(state.latestSummary);
        const baseline = safeObject(summary.baseline);
        const metricsBaseline = safeObject(summary.metrics_baseline);
        const diff = safeObject(summary.diff);
        return {
            cloneTrusted: Boolean(baseline.trusted),
            metricsTrusted: Boolean(metricsBaseline.trusted),
            newFindings: Boolean(baseline.trusted)
                ? Number(safeObject(summary.findings).new || 0)
                : null,
            newClones: Boolean(baseline.trusted)
                ? Number(diff.new_clones || 0)
                : null,
            healthDelta:
                Boolean(metricsBaseline.trusted) &&
                typeof diff.health_delta === "number"
                    ? Number(diff.health_delta)
                    : null,
        };
    }

    baselineDriftSummary(state) {
        const drift = this.baselineDrift(state);
        const parts = [];
        if (drift.newFindings !== null) {
            parts.push(`${drift.newFindings} new`);
        }
        if (drift.newClones !== null) {
            parts.push(`${signedInteger(drift.newClones)} clones`);
        }
        if (drift.healthDelta !== null) {
            parts.push(`${signedInteger(drift.healthDelta)} health`);
        }
        return parts.length > 0 ? parts.join(" · ") : "baseline unavailable";
    }

    async inspectLocalHtmlReport(state) {
        const htmlPath = path.join(
            state.folder.uri.fsPath,
            ".cache",
            "codeclone",
            "report.html"
        );
        if (!(await pathExists(htmlPath))) {
            return {
                htmlPath,
                exists: false,
                stale: false,
                reason: "missing",
                generatedAtUtc: null,
            };
        }
        const stat = await fs.stat(htmlPath);
        let generatedAtUtc = null;
        try {
            const html = await readFileHead(htmlPath);
            const match = html.match(/data-report-generated-at-utc="([^"]+)"/);
            generatedAtUtc = match ? match[1] : null;
        } catch {
            generatedAtUtc = null;
        }
        const generatedAtMs =
            parseUtcTimestamp(generatedAtUtc) ?? Number(stat.mtimeMs || 0);
        const runUpdatedMs = state.lastUpdatedAt ? state.lastUpdatedAt.getTime() : null;
        const staleBecauseOlderThanRun =
            runUpdatedMs !== null && generatedAtMs > 0 && generatedAtMs + 1500 < runUpdatedMs;
        const staleBecauseWorkspaceChanged = Boolean(state.stale);
        const stale = staleBecauseOlderThanRun || staleBecauseWorkspaceChanged;
        let reason = null;
        if (staleBecauseWorkspaceChanged) {
            reason = "workspace-changed";
        } else if (staleBecauseOlderThanRun) {
            reason = "older-than-run";
        }
        return {
            htmlPath,
            exists: true,
            stale,
            reason,
            generatedAtUtc,
        };
    }

    toOverloadedModuleNodes(state, items) {
        return items.map((item) => this.buildOverloadedModuleNode(state, item));
    }

    buildOverloadedModuleNode(state, item) {
        return {
            nodeType: "overloadedModule",
            workspaceKey: state.folder.uri.toString(),
            runId: state.currentRunId,
            item,
            label: item.path,
            description: `${decimal(item.score)} · ${item.source_kind} · report-only`,
            tooltip: `${item.module} · ${number(item.loc)} LOC · ${item.total_deps} deps`,
            icon: new vscode.ThemeIcon("symbol-module"),
            contextValue: "codeclone.overloadedModule",
            command: {
                command: "codeclone.reviewOverloadedModule",
                title: "Review Overloaded Module",
                arguments: [
                    {
                        workspaceKey: state.folder.uri.toString(),
                        runId: state.currentRunId,
                        item,
                        nodeType: "overloadedModule",
                    },
                ],
            },
        };
    }

    currentPriorityQueue(state) {
        const artifacts = safeObject(state.reviewArtifacts);
        const groupIds =
            this.hotspotFocusMode === "recommended"
                ? ["changedFiles", "newRegressions", "productionHotspots"]
                : this.hotspotFocusMode === "all"
                    ? ["changedFiles", "newRegressions", "productionHotspots", "overloadedModules"]
                    : this.activeHotspotGroupIds(state);
        const queue = [];
        const seen = new Set();
        for (const groupId of groupIds) {
            if (groupId === "overloadedModules") {
                for (const node of this.toOverloadedModuleNodes(
                    state,
                    safeArray(artifacts.overloadedModules)
                )) {
                    const key = reviewTargetKey(node);
                    if (!key || seen.has(key)) {
                        continue;
                    }
                    seen.add(key);
                    queue.push(node);
                }
                continue;
            }
            for (const node of this.toFindingNodes(
                state,
                this.reviewArtifactItems(state, groupId)
            )) {
                const key = reviewTargetKey(node);
                if (!key || seen.has(key)) {
                    continue;
                }
                seen.add(key);
                queue.push(node);
            }
        }
        if (
            this.hotspotFocusMode === "recommended" &&
            queue.length === 0 &&
            safeArray(artifacts.overloadedModules).length > 0
        ) {
            return this.toOverloadedModuleNodes(state, safeArray(artifacts.overloadedModules));
        }
        return queue;
    }

    async moveReviewCursor(step) {
        const state = this.getPrimaryState();
        if (!state || !state.currentRunId) {
            await vscode.window.showInformationMessage(
                "Start with Analyze Workspace or Review Changes before starting a review loop."
            );
            return;
        }
        await this.ensureConnected(state.folder);
        await this.refreshReviewArtifacts(state);
        const queue = this.currentPriorityQueue(state);
        if (queue.length === 0) {
            await vscode.window.showInformationMessage(
                "No review-ready items are visible in the current run."
            );
            return;
        }
        const currentKey = reviewTargetKey(this.activeReviewTarget);
        const currentIndex = queue.findIndex(
            (node) => reviewTargetKey(node) === currentKey
        );
        const nextIndex =
            currentIndex < 0
                ? step > 0
                    ? 0
                    : queue.length - 1
                : currentIndex + step;
        if (nextIndex < 0 || nextIndex >= queue.length) {
            await vscode.window.showInformationMessage(
                step > 0
                    ? "Already at the last hotspot in the current priority queue."
                    : "Already at the first hotspot in the current priority queue."
            );
            return;
        }
        const nextNode = queue[nextIndex];
        if (nextNode.nodeType === "overloadedModule") {
            await this.revealOverloadedModuleSource(nextNode);
            return;
        }
        await this.revealFindingSource(nextNode);
    }

    async setHotspotFocusMode() {
        const picked = await vscode.window.showQuickPick(
            HOTSPOT_FOCUS_MODES.map((entry) => ({
                label: entry.label,
                description:
                    entry.id === this.hotspotFocusMode ? "Current" : undefined,
                detail: entry.description,
                modeId: entry.id,
            })),
            {
                title: "Set Hotspot Focus",
                placeHolder: "Select which hotspot groups CodeClone should emphasize",
                matchOnDetail: true,
            }
        );
        if (!picked) {
            return;
        }
        this.hotspotFocusMode = picked.modeId;
        await this.persistHotspotFocusMode();
        this.updateContextKeys();
        this.refreshAllViews();
    }

    async reviewPriorityQueue() {
        const state = this.getPrimaryState();
        if (!state || !state.currentRunId) {
            await vscode.window.showInformationMessage(
                "Start with Analyze Workspace or Review Changes before opening review priorities."
            );
            return;
        }
        try {
            await this.ensureConnected(state.folder);
            await this.refreshReviewArtifacts(state);
            const queue = this.currentPriorityQueue(state);
            if (queue.length === 0) {
                await vscode.window.showInformationMessage(
                    "No review-ready hotspots are visible in the current run."
                );
                return;
            }
            const picked = await vscode.window.showQuickPick(
                queue.map((node) => ({
                    label: node.label,
                    description: node.description,
                    detail: node.tooltip,
                    node,
                })),
                {
                    title: "Review Priorities",
                    placeHolder: "Select the next CodeClone review item",
                    matchOnDetail: true,
                }
            );
            if (picked) {
                if (picked.node.nodeType === "overloadedModule") {
                    await this.reviewOverloadedModule(picked.node);
                } else {
                    await this.reviewFinding(picked.node);
                }
            }
        } catch (error) {
            this.handleError(error, "Could not load the CodeClone review queue.");
        }
    }

    async reviewFinding(node) {
        if (!node || !node.findingId || !node.runId) {
            return;
        }
        const resolved = await this.resolveFindingNode(node);
        if (!resolved) {
            return;
        }
        const picked = await vscode.window.showQuickPick(
            [
                {
                    label: "Reveal source",
                    description: "Recommended",
                    action: "reveal",
                },
                {
                    label: "Peek occurrences",
                    description: "Inspect all reported locations",
                    action: "peek",
                },
                {
                    label: "Open finding detail",
                    description: "Canonical finding view",
                    action: "detail",
                },
                {
                    label: "Show remediation",
                    description: "Suggested next step",
                    action: "remediation",
                },
                {
                    label: "Copy refactor brief",
                    description: "AI handoff",
                    action: "brief",
                },
                {
                    label: "Open in HTML report",
                    description: "If a local HTML report exists",
                    action: "html",
                },
                {
                    label: "Mark as reviewed",
                    description: "Hide from review-focused lists",
                    action: "reviewed",
                },
            ],
            {
                title: "Review Finding",
                placeHolder: `What do you want to do with ${resolved.findingId}?`,
            }
        );
        if (!picked) {
            return;
        }
        if (picked.action === "reveal") {
            await this.revealFindingSource(resolved);
            return;
        }
        if (picked.action === "peek") {
            await this.peekFindingLocations(resolved);
            return;
        }
        if (picked.action === "detail") {
            await this.openFinding(resolved);
            return;
        }
        if (picked.action === "remediation") {
            await this.showRemediation(resolved);
            return;
        }
        if (picked.action === "brief") {
            await this.copyRefactorBrief(resolved);
            return;
        }
        if (picked.action === "html") {
            await this.openInHtmlReport(resolved);
            return;
        }
        if (picked.action === "reviewed") {
            await this.markFindingReviewed(resolved);
        }
    }

    async openFinding(node) {
        const resolved = await this.resolveFindingNode(node);
        if (!resolved) {
            return;
        }
        const state = this.states.get(resolved.workspaceKey);
        try {
            await this.ensureConnected(state.folder);
            const payload =
                resolved.detailPayload ||
                (await this.client.callTool("get_finding", {
                    run_id: resolved.runId,
                    finding_id: resolved.findingId,
                    detail_level: "normal",
                }));
            await this.showMarkdownDocument(renderFindingMarkdown(payload));
        } catch (error) {
            this.handleError(error, `Could not open finding ${resolved.findingId}.`);
        }
    }

    async peekFindingLocations(node) {
        const resolved = await this.resolveFindingNode(node);
        if (!resolved) {
            return;
        }
        const locationCandidates = safeArray(resolved.locations).map((location) => {
            const uri = vscode.Uri.file(location.absolutePath);
            const startLine = Math.max(Number(location.line || 1) - 1, 0);
            const endLine = Math.max(
                Number(location.end_line || location.line || 1) - 1,
                startLine
            );
            const start = new vscode.Position(startLine, 0);
            const end = new vscode.Position(endLine, 0);
            return new vscode.Location(uri, new vscode.Range(start, end));
        });
        const locations = (
            await Promise.all(
                locationCandidates.map(async (entry) => ({
                    entry,
                    exists: await pathExists(entry.uri.fsPath),
                }))
            )
        )
            .filter((entry) => entry.exists)
            .map((entry) => entry.entry);
        if (locations.length === 0) {
            await vscode.window.showInformationMessage(
                "This finding does not expose source locations for Peek."
            );
            return;
        }
        const primary = locations[0];
        try {
            const document = await vscode.workspace.openTextDocument(primary.uri);
            await vscode.window.showTextDocument(document, {preview: true});
            await vscode.commands.executeCommand(
                "editor.action.peekLocations",
                primary.uri,
                primary.range.start,
                locations,
                "peek"
            );
        } catch (error) {
            this.handleError(error, `Could not peek locations for ${resolved.findingId}.`);
        }
    }

    async showRemediation(node) {
        const resolved = await this.resolveFindingNode(node);
        if (!resolved) {
            return;
        }
        const state = this.states.get(resolved.workspaceKey);
        try {
            await this.ensureConnected(state.folder);
            const payload = await this.client.callTool("get_remediation", {
                run_id: resolved.runId,
                finding_id: resolved.findingId,
                detail_level: "normal",
            });
            await this.showMarkdownDocument(renderRemediationMarkdown(payload));
        } catch (error) {
            this.handleError(error, `Could not load remediation for ${resolved.findingId}.`);
        }
    }

    async markFindingReviewed(node) {
        const resolved = await this.resolveFindingNode(node);
        if (!resolved) {
            return;
        }
        const state = this.states.get(resolved.workspaceKey);
        try {
            await this.ensureConnected(state.folder);
            await this.client.callTool("mark_finding_reviewed", {
                run_id: resolved.runId,
                finding_id: resolved.findingId,
            });
            const reviewed = await this.client.callTool("list_reviewed_findings", {
                run_id: resolved.runId,
            });
            state.reviewed = safeArray(reviewed.items);
            this.setActiveReviewTarget({
                ...resolved,
                reviewed: true,
            });
            await this.refreshReviewArtifacts(state);
            this.sessionProvider.refresh();
            this.refreshAllViews();
            await vscode.window.showInformationMessage(
                `Marked ${resolved.findingId} as reviewed.`
            );
        } catch (error) {
            this.handleError(error, `Could not mark ${resolved.findingId} as reviewed.`);
        }
    }

    async copyFindingId(node) {
        const activeNode = this.activeFindingTarget(node);
        if (!activeNode || !activeNode.findingId) {
            return;
        }
        await vscode.env.clipboard.writeText(String(activeNode.findingId));
        await vscode.window.showInformationMessage(
            `Copied finding id ${activeNode.findingId}.`
        );
    }

    async copyFindingContext(node) {
        const resolved = await this.resolveFindingNode(node);
        if (!resolved) {
            return;
        }
        const state = this.states.get(resolved.workspaceKey);
        try {
            await this.ensureConnected(state.folder);
            const payload =
                resolved.detailPayload ||
                (await this.client.callTool("get_finding", {
                    run_id: resolved.runId,
                    finding_id: resolved.findingId,
                    detail_level: "normal",
                }));
            const spread = safeObject(payload.spread);
            const locations = normalizeFindingLocations(state.folder, payload.locations);
            const lines = [
                "# CodeClone Finding Context",
                "",
                `- Workspace: ${state.folder.name}`,
                `- Run: ${resolved.runId}`,
                `- Finding id: ${payload.id}`,
                `- Kind: ${formatKind(payload.kind)}`,
                `- Severity: ${formatSeverity(payload.severity)}`,
                `- Scope: ${payload.scope || "unknown"}`,
                `- Priority: ${compactDecimal(payload.priority)}`,
                `- Spread: ${spread.files || 0} files / ${spread.functions || 0} functions`,
            ];
            if (locations.length > 0) {
                lines.push(
                    "",
                    "## Locations",
                    markdownBulletList(
                        locations.map((location) => {
                            const lineText =
                                location.line !== null && location.end_line !== null
                                    ? `${location.line}-${location.end_line}`
                                    : location.line !== null
                                        ? `${location.line}`
                                        : "?";
                            return `\`${location.path}:${lineText}\``;
                        })
                    )
                );
            }
            await vscode.env.clipboard.writeText(lines.join("\n"));
            await vscode.window.showInformationMessage(
                `Copied finding context for ${resolved.findingId}.`
            );
        } catch (error) {
            this.handleError(error, `Could not copy context for ${resolved.findingId}.`);
        }
    }

    async copyRefactorBrief(node) {
        const resolved = await this.resolveFindingNode(node);
        if (!resolved) {
            return;
        }
        const state = this.states.get(resolved.workspaceKey);
        try {
            await this.ensureConnected(state.folder);
            const [finding, remediation] = await Promise.all([
                resolved.detailPayload ||
                this.client.callTool("get_finding", {
                    run_id: resolved.runId,
                    finding_id: resolved.findingId,
                    detail_level: "normal",
                }),
                this.client.callTool("get_remediation", {
                    run_id: resolved.runId,
                    finding_id: resolved.findingId,
                    detail_level: "normal",
                }),
            ]);
            const steps = safeArray(safeObject(remediation.remediation).steps);
            const lines = [
                "# CodeClone Refactor Brief",
                "",
                `Repository: ${state.folder.name}`,
                `Finding: ${finding.id} (${formatKind(finding.kind)})`,
                `Severity: ${formatSeverity(finding.severity)} · Scope: ${finding.scope || "unknown"} · Priority: ${compactDecimal(finding.priority)}`,
                "",
                "Treat the CodeClone finding and remediation as the canonical source of truth.",
                "Keep behavior unchanged unless the remediation explicitly requires a behavioral shift.",
                "",
                "## Suggested shape",
                safeObject(remediation.remediation).shape || "Use a minimal, behavior-preserving refactor.",
            ];
            if (safeObject(remediation.remediation).why_now) {
                lines.push("", `Why now: ${safeObject(remediation.remediation).why_now}`);
            }
            if (steps.length > 0) {
                lines.push("", "## Steps", markdownBulletList(steps));
            }
            await vscode.env.clipboard.writeText(lines.join("\n"));
            await vscode.window.showInformationMessage(
                `Copied refactor brief for ${resolved.findingId}.`
            );
        } catch (error) {
            this.handleError(error, `Could not build a refactor brief for ${resolved.findingId}.`);
        }
    }

    async openInHtmlReport(node) {
        const resolved = await this.resolveFindingNode(node);
        if (!resolved) {
            return;
        }
        const state = this.states.get(resolved.workspaceKey);
        const htmlState = await this.inspectLocalHtmlReport(state);
        if (!htmlState.exists) {
            const choice = await vscode.window.showInformationMessage(
                "No local HTML report is available for this workspace yet.",
                "Open finding detail",
                "Reveal source"
            );
            if (choice === "Open finding detail") {
                await this.openFinding(resolved);
            } else if (choice === "Reveal source") {
                await this.revealFindingSource(resolved);
            }
            return;
        }
        let anchor = `finding-${resolved.findingId}`;
        try {
            await this.ensureConnected(state.folder);
            const payload =
                resolved.detailPayload ||
                (await this.client.callTool("get_finding", {
                    run_id: resolved.runId,
                    finding_id: resolved.findingId,
                    detail_level: "normal",
                }));
            if (payload && payload.html_anchor) {
                anchor = String(payload.html_anchor);
            }
        } catch {
            // Keep the deterministic fallback anchor when detail lookup fails.
        }
        if (htmlState.stale) {
            const staleWarning =
                htmlState.reason === "workspace-changed"
                    ? "The local HTML report may be stale because the workspace changed after this run."
                    : "The local HTML report looks older than the current CodeClone run.";
            const generatedSuffix = htmlState.generatedAtUtc
                ? ` Report generated at ${htmlState.generatedAtUtc}.`
                : "";
            const choice = await vscode.window.showWarningMessage(
                `${staleWarning}${generatedSuffix}`,
                "Open anyway",
                "Open finding detail",
                "Reveal source"
            );
            if (choice === "Open anyway") {
                const uri = vscode.Uri.file(htmlState.htmlPath).with({fragment: anchor});
                await vscode.env.openExternal(uri);
                return;
            }
            if (choice === "Open finding detail") {
                await this.openFinding(resolved);
                return;
            }
            if (choice === "Reveal source") {
                await this.revealFindingSource(resolved);
                return;
            }
            return;
        }
        const uri = vscode.Uri.file(htmlState.htmlPath).with({fragment: anchor});
        await vscode.env.openExternal(uri);
    }

    async revealFindingSource(node) {
        const resolved = await this.resolveFindingNode(node);
        if (!resolved) {
            return;
        }
        const state = this.states.get(resolved.workspaceKey);
        const location = firstNormalizedLocation(state.folder, resolved.locations);
        if (!location || !location.path) {
            await vscode.window.showInformationMessage(
                "This item does not expose a source location."
            );
            return;
        }
        await this.revealWorkspacePath(
            state.folder,
            location.path,
            location.line ?? undefined,
            location.end_line ?? undefined
        );
    }

    async revealOverloadedModuleSource(node) {
        const activeNode = this.activeOverloadedModuleTarget(node);
        if (!activeNode) {
            return;
        }
        const state = this.states.get(activeNode.workspaceKey);
        if (!state) {
            return;
        }
        const resolved = {
            ...activeNode,
            nodeType: "overloadedModule",
        };
        this.setActiveReviewTarget(resolved);
        await this.revealWorkspacePath(state.folder, activeNode.item.path);
    }

    /**
     * @param {any} folder
     * @param {string} relativePath
     * @param {number | undefined} [line]
     * @param {number | undefined} [endLine]
     */
    async revealWorkspacePath(folder, relativePath, line = undefined, endLine = undefined) {
        const absolutePath = resolveWorkspacePath(folder.uri.fsPath, relativePath);
        if (!absolutePath) {
            await vscode.window.showWarningMessage(
                "CodeClone ignored a source path outside the workspace root."
            );
            return;
        }
        const fileUri = vscode.Uri.file(absolutePath);
        try {
            const document = await vscode.workspace.openTextDocument(fileUri);
            const editor = await vscode.window.showTextDocument(document, {
                preview: true,
            });
            if (typeof line === "number") {
                const span = revealLineSpan(line, endLine, document.lineCount);
                if (!span) {
                    return;
                }
                const position = new vscode.Position(span.startLine, 0);
                const endPosition = new vscode.Position(
                    span.finalLine,
                    document.lineAt(span.finalLine).range.end.character
                );
                const range = new vscode.Range(position, endPosition);
                editor.selection = new vscode.Selection(position, endPosition);
                editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
                this.flashRevealRange(editor, range);
            }
        } catch (error) {
            this.handleError(error, `Could not open ${relativePath}.`);
        }
    }

    flashRevealRange(editor, range) {
        if (this.revealDecorationTimeout) {
            clearTimeout(this.revealDecorationTimeout);
            this.revealDecorationTimeout = null;
        }
        editor.setDecorations(this.revealDecoration, [range]);
        this.revealDecorationTimeout = setTimeout(() => {
            try {
                editor.setDecorations(this.revealDecoration, []);
            } catch {
                // Ignore editor disposal during timeout cleanup.
            }
            this.revealDecorationTimeout = null;
        }, 3500);
    }

    async showHelpTopic(arg) {
        const folder = this.getPreferredFolder();
        if (!folder) {
            return;
        }
        const topic =
            typeof arg === "string"
                ? arg
                : arg && typeof arg.topic === "string"
                    ? arg.topic
                    : await this.pickHelpTopic();
        if (!topic) {
            return;
        }
        await this.persistLastHelpTopic(topic);
        if (!vscode.workspace.isTrusted) {
            await this.showMarkdownDocument(renderRestrictedModeMarkdown(topic));
            return;
        }
        try {
            await this.ensureConnected(folder);
            const payload = await this.client.callTool("help", {
                topic,
                detail: "normal",
            });
            await this.showMarkdownDocument(renderHelpMarkdown(topic, payload));
        } catch (error) {
            this.handleError(error, `Could not load help for ${topic}.`);
        }
    }

    async openSetupHelp() {
        await this.showMarkdownDocument(renderSetupMarkdown());
    }

    async openOverloadedModule(node) {
        const activeNode = this.activeOverloadedModuleTarget(node);
        if (!activeNode) {
            return;
        }
        this.setActiveReviewTarget(activeNode);
        await this.showMarkdownDocument(renderOverloadedModuleMarkdown(activeNode.item));
    }

    async reviewOverloadedModule(node) {
        const activeNode = this.activeOverloadedModuleTarget(node);
        if (!activeNode) {
            return;
        }
        this.setActiveReviewTarget(activeNode);
        const picked = await vscode.window.showQuickPick(
            [
                {
                    label: "Reveal module source",
                    description: "Recommended",
                    action: "reveal",
                },
                {
                    label: "Show report-only detail",
                    description: "Open Overloaded Module summary",
                    action: "detail",
                },
                {
                    label: "Copy report-only brief",
                    description: "AI handoff",
                    action: "brief",
                },
            ],
            {
                title: "Review Overloaded Module",
                placeHolder: `What do you want to do with ${activeNode.item.path}?`,
            }
        );
        if (!picked) {
            return;
        }
        if (picked.action === "reveal") {
            await this.revealOverloadedModuleSource(activeNode);
            return;
        }
        if (picked.action === "brief") {
            await this.copyOverloadedModuleBrief(activeNode);
            return;
        }
        await this.openOverloadedModule(activeNode);
    }

    async copyOverloadedModuleBrief(node) {
        const activeNode = this.activeOverloadedModuleTarget(node);
        if (!activeNode) {
            return;
        }
        this.setActiveReviewTarget(activeNode);
        const item = activeNode.item;
        const reasons = safeArray(item.candidate_reasons);
        const lines = [
            "# CodeClone Report-only Module Brief",
            "",
            `Repository: ${this.states.get(activeNode.workspaceKey)?.folder.name || "unknown"}`,
            `Module: ${item.module}`,
            `Path: ${item.path}`,
            `Source kind: ${item.source_kind || "unknown"}`,
            `Candidate score: ${decimal(item.score)}`,
            "",
            "Treat this as a report-only structural signal, not as a blocking finding or gate result.",
            "Focus on responsibility overload and dependency pressure before touching behavior.",
            "",
            "## Module profile",
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
            lines.push(
                "",
                "## Why CodeClone highlighted this module",
                markdownBulletList(reasons)
            );
        }
        await vscode.env.clipboard.writeText(lines.join("\n"));
        await vscode.window.showInformationMessage(
            `Copied report-only brief for ${item.path}.`
        );
    }

    async clearSessionState() {
        const folder = this.getPreferredFolder();
        if (!folder) {
            return;
        }
        try {
            await this.ensureConnected(folder);
            await this.client.callTool("clear_session_runs", {});
            for (const state of this.states.values()) {
                state.currentRunId = null;
                state.latestSummary = null;
                state.metricsSummary = null;
                state.latestTriage = null;
                state.changedSummary = null;
                state.analysisSettings = null;
                state.reviewed = [];
                state.reviewArtifacts = emptyReviewArtifacts();
                state.gitSnapshot = null;
                state.stale = false;
                state.staleReason = null;
                state.groupCache.clear();
            }
            this.clearActiveReviewTarget();
            this.rebuildFileDecorations();
            this.updateContextKeys();
            this.updateStatusBar();
            this.refreshAllViews();
            await vscode.window.showInformationMessage(
                "CodeClone MCP session state cleared."
            );
        } catch (error) {
            this.handleError(error, "Could not clear CodeClone MCP session state.");
        }
    }

    async pickHelpTopic() {
        const picked = await vscode.window.showQuickPick(
            HELP_TOPICS.map((topic) => ({
                label: topic.replace(/_/g, " "),
                description:
                    topic === this.lastHelpTopic ? "Last opened" : "CodeClone MCP help topic",
                topic,
            })),
            {
                title: "Open Help Topic",
                placeHolder: "Select a CodeClone MCP help topic",
            }
        );
        return picked ? picked.topic : null;
    }

    async showMarkdownDocument(markdown) {
        const document = await vscode.workspace.openTextDocument({
            content: markdown,
            language: "markdown",
        });
        await vscode.window.showTextDocument(document, {
            preview: true,
        });
    }

    provideReviewCodeLenses(document) {
        const target = this.activeReviewTarget;
        if (!target) {
            return [];
        }
        if (target.nodeType === "overloadedModule") {
            const state = this.states.get(target.workspaceKey);
            if (!state) {
                return [];
            }
            const relativePath = workspaceRelativePath(state.folder, document.uri.fsPath);
            if (relativePath !== normalizeRelativePath(target.item.path)) {
                return [];
            }
            const range = new vscode.Range(0, 0, 0, 0);
            return [
                new vscode.CodeLens(range, {
                    command: "codeclone.previousReviewItem",
                    title: "$(arrow-up) Previous hotspot",
                }),
                new vscode.CodeLens(range, {
                    command: "codeclone.nextReviewItem",
                    title: "$(arrow-down) Next hotspot",
                }),
                new vscode.CodeLens(range, {
                    command: "codeclone.openOverloadedModule",
                    title: "$(symbol-module) Report-only detail",
                    arguments: [target],
                }),
                new vscode.CodeLens(range, {
                    command: "codeclone.copyOverloadedModuleBrief",
                    title: "$(copy) Copy report-only brief",
                    arguments: [target],
                }),
            ];
        }
        const state = this.states.get(target.workspaceKey);
        if (!state) {
            return [];
        }
        const matchingLocations = safeArray(target.locations).filter(
            (location) => location.absolutePath === document.uri.fsPath
        );
        if (matchingLocations.length === 0) {
            return [];
        }
        const primaryLocation = matchingLocations[0];
        const startLine = Math.max(Number(primaryLocation.line || 1) - 1, 0);
        const range = new vscode.Range(startLine, 0, startLine, 0);
        return [
            new vscode.CodeLens(range, {
                command: "codeclone.previousReviewItem",
                title: "$(arrow-up) Previous hotspot",
            }),
            new vscode.CodeLens(range, {
                command: "codeclone.nextReviewItem",
                title: "$(arrow-down) Next hotspot",
            }),
            new vscode.CodeLens(range, {
                command: "codeclone.peekFindingLocations",
                title: "$(references) Peek occurrences",
                arguments: [target],
            }),
            new vscode.CodeLens(range, {
                command: "codeclone.showRemediation",
                title: "$(wrench) Remediation",
                arguments: [target],
            }),
            ...(!target.reviewed
                ? [
                    new vscode.CodeLens(range, {
                        command: "codeclone.markFindingReviewed",
                        title: "$(pass) Mark reviewed",
                        arguments: [target],
                    }),
                ]
                : []),
        ];
    }

    currentAnalysisSettings(state) {
        if (!state) {
            return null;
        }
        return state.analysisSettings || this.configuredAnalysisSettings(state.folder);
    }

    pendingAnalysisSettings(state) {
        if (!state) {
            return null;
        }
        const currentSettings = this.currentAnalysisSettings(state);
        const configuredSettings = this.configuredAnalysisSettings(state.folder);
        return sameAnalysisSettings(currentSettings, configuredSettings)
            ? null
            : configuredSettings;
    }

    async getOverviewChildren(node) {
        const state = this.getPrimaryState();
        if (!state || !state.latestSummary) {
            return [];
        }
        const currentAnalysisSettings = this.currentAnalysisSettings(state);
        const pendingAnalysisSettings = this.pendingAnalysisSettings(state);
        const reviewCounts = {
            changed: this.reviewArtifactCount(state, "changedFiles"),
            new: this.reviewArtifactCount(state, "newRegressions"),
            production: this.reviewArtifactCount(state, "productionHotspots"),
            overloadedModules: this.reviewArtifactCount(state, "overloadedModules"),
        };
        const baselineDrift = this.baselineDrift(state);
        if (!node) {
            const sections = [
                {
                    nodeType: "section",
                    id: "overview.health",
                    label:
                        String(state.latestSummary.health_scope || "repository") === "repository"
                            ? "Repository Health"
                            : "Structural Health",
                    description:
                        baselineDrift.healthDelta !== null
                            ? `${state.latestSummary.health.score}/${state.latestSummary.health.grade} · ${signedInteger(
                                baselineDrift.healthDelta
                            )} vs baseline`
                            : `${state.latestSummary.health.score}/${state.latestSummary.health.grade}`,
                    icon: new vscode.ThemeIcon("heart"),
                },
                {
                    nodeType: "section",
                    id: "overview.run",
                    label: "Current Run",
                    description: state.stale
                        ? `${state.currentRunId} · stale`
                        : currentAnalysisSettings
                            ? `${state.currentRunId} · ${currentAnalysisSettings.label.toLowerCase()}`
                            : `${state.currentRunId} · ${state.latestSummary.cache.freshness}`,
                    icon: new vscode.ThemeIcon("pulse"),
                },
                {
                    nodeType: "section",
                    id: "overview.triage",
                    label: "Priority Review",
                    description: `${reviewCounts.production} production · ${reviewCounts.new} new`,
                    icon: new vscode.ThemeIcon("inspect"),
                },
            ];
            if (state.changedSummary) {
                sections.push({
                    nodeType: "section",
                    id: "overview.changed",
                    label: "Changed Scope",
                    description: `${state.changedSummary.changed_files} files · ${state.changedSummary.verdict}`,
                    icon: new vscode.ThemeIcon("git-commit"),
                });
            }
            if (safeObject(state.metricsSummary).overloaded_modules) {
                const overloadedModules = safeObject(state.metricsSummary).overloaded_modules;
                sections.push({
                    nodeType: "section",
                    id: "overview.god",
                    label: "Overloaded Modules",
                    description: `${overloadedModules.candidates} candidates · top ${decimal(overloadedModules.top_score)} (report-only)`,
                    icon: new vscode.ThemeIcon("symbol-module"),
                });
            }
            return sections;
        }
        if (node.id === "overview.health") {
            const dimensions = safeObject(state.latestSummary.health.dimensions);
            return [
                this.detailNode(
                    "Scope",
                    capitalize(String(state.latestSummary.health_scope || "repository"))
                ),
                this.detailNode("Score", `${state.latestSummary.health.score}/${state.latestSummary.health.grade}`),
                this.detailNode("Clones", number(dimensions.clones)),
                this.detailNode("Complexity", number(dimensions.complexity)),
                this.detailNode("Coupling", number(dimensions.coupling)),
                this.detailNode("Cohesion", number(dimensions.cohesion)),
                this.detailNode("Dead code", number(dimensions.dead_code)),
                this.detailNode("Dependencies", number(dimensions.dependencies)),
                this.detailNode("Coverage", number(dimensions.coverage)),
                this.detailNode(
                    "Health delta",
                    baselineDrift.healthDelta !== null
                        ? `${signedInteger(baselineDrift.healthDelta)} vs metrics baseline`
                        : "metrics baseline unavailable"
                ),
            ];
        }
        if (node.id === "overview.run") {
            const inventory = safeObject(state.latestSummary.inventory);
            return [
                this.detailNode("Workspace", state.folder.name),
                this.detailNode("Run ID", state.currentRunId),
                this.detailNode(
                    "Analysis depth",
                    currentAnalysisSettings ? currentAnalysisSettings.label : "unknown"
                ),
                this.detailNode(
                    "Threshold profile",
                    currentAnalysisSettings
                        ? currentAnalysisSettings.thresholdSummary
                        : "unknown"
                ),
                ...(pendingAnalysisSettings
                    ? [
                        this.detailNode(
                            "Next run",
                            `${pendingAnalysisSettings.label} · pending`
                        ),
                    ]
                    : []),
                this.detailNode(
                    "Freshness",
                    state.stale ? `stale · ${state.staleReason}` : "current"
                ),
                this.detailNode("Files", number(inventory.files)),
                this.detailNode("Parsed lines", number(inventory.lines)),
                this.detailNode("Callables", number(inventory.functions)),
                this.detailNode("Classes", number(inventory.classes)),
                this.detailNode("Baseline", formatBaselineState(state.latestSummary.baseline)),
                this.detailNode(
                    "Metrics baseline",
                    formatBaselineState(state.latestSummary.metrics_baseline)
                ),
                this.detailNode("Baseline drift", this.baselineDriftSummary(state)),
                this.detailNode("Cache", formatCacheSummary(state.latestSummary.cache)),
            ];
        }
        if (node.id === "overview.triage") {
            const nextAction = this.describeNextBestAction(state);
            const triageFindings = safeObject(state.latestTriage?.findings);
            const summaryFindings = safeObject(state.latestSummary.findings);
            return [
                this.detailNode("Next best action", nextAction.label),
                this.detailNode("Focus mode", focusModeSpec(this.hotspotFocusMode).label),
                this.detailNode(
                    "Focus",
                    capitalize(String(state.latestTriage?.focus || "production").replace(/_/g, " "))
                ),
                this.detailNode(
                    "Health scope",
                    capitalize(String(state.latestSummary.health_scope || "repository"))
                ),
                this.detailNode(
                    "Analysis depth",
                    currentAnalysisSettings ? currentAnalysisSettings.label : "unknown"
                ),
                this.detailNode("New regressions", number(reviewCounts.new)),
                this.detailNode(
                    "New by source kind",
                    formatSourceKindSummary(summaryFindings.new_by_source_kind)
                ),
                this.detailNode("Production hotspots", number(reviewCounts.production)),
                this.detailNode("Outside focus", number(triageFindings.outside_focus)),
                this.detailNode(
                    "New clones",
                    baselineDrift.newClones !== null
                        ? `${signedInteger(baselineDrift.newClones)} vs clone baseline`
                        : "baseline unavailable"
                ),
                this.detailNode(
                    "Changed files",
                    state.changedSummary
                        ? `${number(reviewCounts.changed)} visible · ${state.changedSummary.verdict}`
                        : "not analyzed"
                ),
                this.detailNode("Reviewed hidden", number(state.reviewed.length)),
            ];
        }
        if (node.id === "overview.changed") {
            return [
                this.detailNode(
                    "Focus",
                    capitalize(String(state.changedSummary.focus || "changed_paths").replace(/_/g, " "))
                ),
                this.detailNode("Changed files", number(state.changedSummary.changed_files)),
                this.detailNode("Verdict", String(state.changedSummary.verdict)),
                this.detailNode("New findings", number(state.changedSummary.new_findings)),
                this.detailNode(
                    "New by source kind",
                    formatSourceKindSummary(state.changedSummary.new_by_source_kind)
                ),
                this.detailNode("Resolved findings", number(state.changedSummary.resolved_findings)),
                this.detailNode(
                    "Health delta",
                    typeof state.changedSummary.health_delta === "number"
                        ? String(state.changedSummary.health_delta)
                        : "n/a"
                ),
            ];
        }
        if (node.id === "overview.god") {
            const overloadedModules = safeObject(state.metricsSummary).overloaded_modules;
            return [
                this.detailNode("Candidates", number(overloadedModules.candidates)),
                this.detailNode("Ranked modules", number(overloadedModules.total)),
                this.detailNode("Top score", decimal(overloadedModules.top_score)),
                this.detailNode("Average score", decimal(overloadedModules.average_score)),
                this.detailNode("Population", String(overloadedModules.population_status)),
                this.detailNode(
                    "Review surface",
                    `${number(reviewCounts.overloadedModules)} visible in Hotspots`
                ),
            ];
        }
        return [];
    }

    async getHotspotsChildren(node) {
        const state = this.getPrimaryState();
        if (!state || !state.latestSummary) {
            return [];
        }
        if (!node) {
            const groups = this.activeHotspotGroupIds(state).map((groupId) =>
                HOTSPOT_GROUPS.find((group) => group.id === groupId)
            ).filter(Boolean);
            if (groups.length === 0) {
                return [
                    {
                        nodeType: "message",
                        label:
                            this.hotspotFocusMode === "recommended"
                                ? "Nothing needs review in the current run."
                                : `No items are visible in ${focusModeSpec(this.hotspotFocusMode).label} focus.`,
                        icon: new vscode.ThemeIcon(
                            state.stale ? "warning" : "circle-slash"
                        ),
                    },
                ];
            }
            return groups.map((group) => ({
                nodeType: "group",
                groupId: group.id,
                label: group.label,
                description: this.describeGroup(group.id, state),
                icon: new vscode.ThemeIcon(group.icon),
                workspaceKey: state.folder.uri.toString(),
            }));
        }
        return this.getHotspotGroupChildren(state, node.groupId);
    }

    async getSessionChildren(node) {
        const state = this.getPrimaryState();
        if (!node && (!state || !state.latestSummary)) {
            return [];
        }
        if (!node) {
            return [
                {
                    nodeType: "section",
                    id: "session.server",
                    label: "Local Server",
                    description: this.connectionInfo.connected ? "ready" : "not connected",
                    icon: new vscode.ThemeIcon("plug"),
                },
                {
                    nodeType: "section",
                    id: "session.run",
                    label: "Current Run",
                    description:
                        state && state.currentRunId
                            ? `${state.currentRunId}${state.stale ? " · stale" : ""}`
                            : "none",
                    icon: new vscode.ThemeIcon("pulse"),
                },
                {
                    nodeType: "section",
                    id: "session.reviewed",
                    label: "Reviewed Findings",
                    description: state ? `${state.reviewed.length}` : "0",
                    icon: new vscode.ThemeIcon("pass"),
                },
                {
                    nodeType: "section",
                    id: "session.help",
                    label: "Help Topics",
                    description: `${HELP_TOPICS.length} topics`,
                    icon: new vscode.ThemeIcon("question"),
                },
            ];
        }
        if (node.id === "session.server") {
            const launch = this.connectionInfo.launchSpec;
            return [
                this.detailNode("Connected", formatBooleanWord(this.connectionInfo.connected)),
                this.detailNode(
                    "CodeClone version",
                    this.connectionInfo.serverInfo ? this.connectionInfo.serverInfo.version : "unknown"
                ),
                this.detailNode("Available tools", number(this.connectionInfo.toolCount)),
                this.detailNode(
                    "Launcher",
                    launch ? `${launch.command} ${launch.args.join(" ")}`.trim() : "not started"
                ),
            ];
        }
        if (node.id === "session.run") {
            if (!state || !state.latestSummary) {
                return [
                    this.detailNode(
                        "Run",
                        "Run Analyze Workspace or Review Changes to create the first run."
                    ),
                ];
            }
            const currentAnalysisSettings = this.currentAnalysisSettings(state);
            const pendingAnalysisSettings = this.pendingAnalysisSettings(state);
            return [
                this.detailNode("Workspace", state.folder.name),
                this.detailNode("Run ID", state.currentRunId),
                this.detailNode("Scope", formatRunScope(state.lastScope)),
                this.detailNode("Mode", state.latestSummary.mode),
                this.detailNode(
                    "Analysis depth",
                    currentAnalysisSettings ? currentAnalysisSettings.label : "unknown"
                ),
                ...(pendingAnalysisSettings
                    ? [
                        this.detailNode(
                            "Next run",
                            `${pendingAnalysisSettings.label} · pending`
                        ),
                    ]
                    : []),
                this.detailNode(
                    "Freshness",
                    state.stale ? `stale · ${state.staleReason}` : "current"
                ),
                this.detailNode("Cache freshness", state.latestSummary.cache.freshness),
                this.detailNode("Updated", state.lastUpdatedAt ? state.lastUpdatedAt.toLocaleString() : "unknown"),
            ];
        }
        if (node.id === "session.reviewed") {
            if (!state || !state.currentRunId || state.reviewed.length === 0) {
                return [
                    {
                        nodeType: "message",
                        label: "Nothing has been marked reviewed in this session yet.",
                        icon: new vscode.ThemeIcon("circle-slash"),
                    },
                ];
            }
            return state.reviewed.map((entry) => {
                const finding = safeObject(entry.finding);
                return this.buildFindingNode(
                    state,
                    finding.id || entry.finding_id,
                    finding,
                    entry.note || null,
                    true
                );
            });
        }
        if (node.id === "session.help") {
            return HELP_TOPICS.map((topic) => ({
                nodeType: "helpTopic",
                topic,
                label: topic,
                description: "Open MCP semantic guide",
                icon: new vscode.ThemeIcon("question"),
            }));
        }
        return [];
    }

    async getHotspotGroupChildren(state, groupId) {
        if (state.groupCache.has(groupId)) {
            return state.groupCache.get(groupId);
        }
        try {
            await this.ensureConnected(state.folder);
            if (!state.currentRunId) {
                return [];
            }
            let nodes = [];
            switch (groupId) {
                case "newRegressions":
                    nodes = this.toFindingNodes(
                        state,
                        this.reviewArtifactItems(state, "newRegressions")
                    );
                    break;
                case "productionHotspots":
                    nodes = this.toFindingNodes(
                        state,
                        this.reviewArtifactItems(state, "productionHotspots")
                    );
                    break;
                case "changedFiles":
                    if (!state.changedSummary) {
                        nodes = [
                            {
                                nodeType: "message",
                                label: "Run Review Changes to load changed-scope findings.",
                                icon: new vscode.ThemeIcon("info"),
                            },
                        ];
                        break;
                    }
                    nodes = this.toFindingNodes(
                        state,
                        this.reviewArtifactItems(state, "changedFiles")
                    );
                    break;
                case "overloadedModules":
                    nodes = this.toOverloadedModuleNodes(
                        state,
                        this.reviewArtifactItems(state, "overloadedModules")
                    );
                    break;
                default:
                    nodes = [];
            }
            if (!nodes || nodes.length === 0) {
                nodes = [
                    {
                        nodeType: "message",
                        label: this.emptyGroupMessage(groupId),
                        icon: new vscode.ThemeIcon("circle-slash"),
                    },
                ];
            }
            state.groupCache.set(groupId, nodes);
            return nodes;
        } catch (error) {
            return [
                {
                    nodeType: "message",
                    label: `Error: ${error.message}`,
                    icon: new vscode.ThemeIcon("error"),
                },
            ];
        }
    }

    toFindingNodes(state, items) {
        return items.map((item) =>
            this.buildFindingNode(state, item.id, item, null, false)
        );
    }

    buildFindingNode(state, findingId, item, note, reviewed) {
        const spread = safeObject(item.spread);
        const novelty = formatNovelty(item.novelty);
        const descriptionParts = [];
        if (novelty) {
            descriptionParts.push(novelty);
        }
        descriptionParts.push(formatSeverity(item.severity));
        descriptionParts.push(item.scope || "unknown");
        descriptionParts.push(`p${compactDecimal(item.priority || 0)}`);
        return {
            nodeType: "finding",
            workspaceKey: state.folder.uri.toString(),
            runId: state.currentRunId,
            findingId,
            label: formatKind(item.kind),
            description: descriptionParts.join(" · "),
            tooltip:
                `${findingId}\n${spread.files || 0} files / ${spread.functions || 0} functions` +
                (novelty ? `\nNovelty: ${novelty}` : "") +
                (note ? `\nNote: ${note}` : ""),
            icon: findingIcon(item.severity),
            locations: item.locations || [],
            contextValue: reviewed ? "codeclone.reviewedFinding" : "codeclone.finding",
            reviewed,
            command: {
                command: "codeclone.reviewFinding",
                title: "Review Finding",
                arguments: [
                    {
                        workspaceKey: state.folder.uri.toString(),
                        runId: state.currentRunId,
                        findingId,
                        locations: item.locations || [],
                        novelty: item.novelty || "",
                    },
                ],
            },
        };
    }

    describeGroup(groupId, state) {
        switch (groupId) {
            case "newRegressions":
                return `${this.reviewArtifactCount(state, "newRegressions")} new`;
            case "productionHotspots":
                return `${this.reviewArtifactCount(state, "productionHotspots")} production`;
            case "changedFiles":
                return state.changedSummary
                    ? `${this.reviewArtifactCount(state, "changedFiles")} visible · ${state.changedSummary.verdict}`
                    : "not analyzed";
            case "overloadedModules":
                return `${this.reviewArtifactCount(state, "overloadedModules")} report-only`;
            default:
                return "";
        }
    }

    emptyGroupMessage(groupId) {
        switch (groupId) {
            case "newRegressions":
                return "No baseline-new regressions are visible.";
            case "productionHotspots":
                return "No production hotspots are visible.";
            case "changedFiles":
                return "No findings touching changed files are visible.";
            case "overloadedModules":
                return "No report-only Overloaded Module candidates are visible.";
            default:
                return "Nothing is visible in this category.";
        }
    }

    shouldShowGroup(groupId, state) {
        const specificMode = isSpecificFocusMode(this.hotspotFocusMode);
        if (specificMode) {
            const allowed =
                /** @type {any} */ (HOTSPOT_GROUPS_BY_MODE)[this.hotspotFocusMode] ||
                HOTSPOT_GROUPS_BY_MODE.recommended;
            if (!allowed.includes(groupId)) {
                return false;
            }
        }
        switch (groupId) {
            case "newRegressions":
                return specificMode || this.reviewArtifactCount(state, "newRegressions") > 0;
            case "productionHotspots":
                return (
                    specificMode || this.reviewArtifactCount(state, "productionHotspots") > 0
                );
            case "changedFiles":
                if (!state.changedSummary) {
                    return this.hotspotFocusMode === "changed";
                }
                return specificMode || this.reviewArtifactCount(state, "changedFiles") > 0;
            case "overloadedModules":
                return specificMode || this.reviewArtifactCount(state, "overloadedModules") > 0;
            default:
                return false;
        }
    }

    describeNextBestAction(state) {
        const analysisSettings = this.currentAnalysisSettings(state);
        if (state.stale) {
            return {
                label: state.lastScope === "changed" ? "Review changes again" : "Refresh stale run",
                command:
                    state.lastScope === "changed"
                        ? "codeclone.analyzeChangedFiles"
                        : "codeclone.refreshCurrentRun",
                title:
                    state.lastScope === "changed"
                        ? "Review changes again"
                        : "Refresh stale run",
            };
        }
        if (this.reviewArtifactCount(state, "changedFiles") > 0) {
            return {
                label: "Review changed-files hotspots",
                command: "codeclone.reviewPriorityQueue",
                title: "Review changed-files hotspots",
            };
        }
        if (this.reviewArtifactCount(state, "newRegressions") > 0) {
            return {
                label: "Review new regressions",
                command: "codeclone.reviewPriorityQueue",
                title: "Review new regressions",
            };
        }
        if (this.reviewArtifactCount(state, "productionHotspots") > 0) {
            return {
                label: "Review production hotspots",
                command: "codeclone.reviewPriorityQueue",
                title: "Review production hotspots",
            };
        }
        if (this.reviewArtifactCount(state, "overloadedModules") > 0) {
            return {
                label: "Inspect report-only Overloaded Modules",
                command: "codeclone.focusHotspots",
                title: "Inspect report-only Overloaded Modules",
            };
        }
        if (
            analysisSettings &&
            analysisSettings.profileId === ANALYSIS_PROFILE_DEFAULTS
        ) {
            return {
                label: "Adjust analysis depth",
                command: "codeclone.setAnalysisProfile",
                title: "Adjust analysis depth",
            };
        }
        return {
            label: "Repository looks structurally quiet",
            command: "codeclone.focusHotspots",
            title: "Open hotspots",
        };
    }

    detailNode(label, description, command) {
        return {
            nodeType: "detail",
            label,
            description,
            icon: new vscode.ThemeIcon("circle-small-filled"),
            command,
        };
    }

    createTreeItem(node) {
        let item;
        switch (node.nodeType) {
            case "section": {
                item = new vscode.TreeItem(
                    node.label,
                    vscode.TreeItemCollapsibleState.Expanded
                );
                item.id = node.id;
                item.description = node.description;
                item.iconPath = node.icon;
                item.command = node.command;
                break;
            }
            case "group": {
                item = new vscode.TreeItem(
                    node.label,
                    vscode.TreeItemCollapsibleState.Collapsed
                );
                item.id = `${node.workspaceKey}:${node.groupId}`;
                item.description = node.description;
                item.iconPath = node.icon;
                break;
            }
            case "finding": {
                item = new vscode.TreeItem(
                    node.label,
                    vscode.TreeItemCollapsibleState.None
                );
                item.description = node.description;
                item.tooltip = node.tooltip;
                item.iconPath = node.icon;
                item.contextValue = node.contextValue || "codeclone.finding";
                item.command = node.command;
                break;
            }
            case "overloadedModule": {
                item = new vscode.TreeItem(
                    node.label,
                    vscode.TreeItemCollapsibleState.None
                );
                item.description = node.description;
                item.tooltip = node.tooltip;
                item.iconPath = node.icon;
                item.contextValue = "codeclone.overloadedModule";
                item.command = node.command;
                break;
            }
            case "helpTopic": {
                item = new vscode.TreeItem(
                    node.label,
                    vscode.TreeItemCollapsibleState.None
                );
                item.description = node.description;
                item.iconPath = node.icon;
                item.contextValue = "codeclone.helpTopic";
                item.command = {
                    command: "codeclone.showHelpTopic",
                    title: "Show Help Topic",
                    arguments: [node.topic],
                };
                break;
            }
            case "detail": {
                item = new vscode.TreeItem(
                    node.label,
                    vscode.TreeItemCollapsibleState.None
                );
                item.description = node.description;
                item.iconPath = node.icon;
                item.command = node.command;
                break;
            }
            case "message":
            default: {
                item = new vscode.TreeItem(
                    node.label,
                    vscode.TreeItemCollapsibleState.None
                );
                item.iconPath = node.icon || new vscode.ThemeIcon("info");
                item.description = node.description;
                break;
            }
        }
        item.accessibilityInformation = treeAccessibilityInformation(node);
        return item;
    }

    refreshAllViews() {
        if (this.disposed) {
            return;
        }
        this.overviewProvider.refresh();
        this.hotspotsProvider.refresh();
        this.sessionProvider.refresh();
        this.reviewCodeLensProvider.refresh();
        this.updateViewChrome();
    }

    updateViewChrome() {
        if (this.disposed) {
            return;
        }
        const state = this.getPrimaryState();
        if (this.overviewView) {
            this.overviewView.badge = undefined;
            this.overviewView.description = state?.stale ? "Stale" : undefined;
        }
        if (this.hotspotsView) {
            this.hotspotsView.description = focusModeSpec(this.hotspotFocusMode).label;
            this.hotspotsView.message =
                state && state.stale ? staleMessage(state.staleReason) : undefined;
            const newCount = Number(
                this.reviewArtifactCount(state, "newRegressions")
            );
            const productionCount = Number(
                this.reviewArtifactCount(state, "productionHotspots")
            );
            const changedCount = Number(this.reviewArtifactCount(state, "changedFiles"));
            const actionableCount = Math.max(
                newCount + productionCount,
                changedCount
            );
            const overloadedModuleCount = Number(
                this.reviewArtifactCount(state, "overloadedModules")
            );
            let badgeValue = 0;
            let badgeTooltip = "";
            switch (this.hotspotFocusMode) {
                case "new":
                    badgeValue = newCount;
                    badgeTooltip = `${newCount} new regressions are visible in Hotspots`;
                    break;
                case "production":
                    badgeValue = productionCount;
                    badgeTooltip = `${productionCount} production hotspots are visible in Hotspots`;
                    break;
                case "changed":
                    badgeValue = changedCount;
                    badgeTooltip = `${changedCount} changed-files review items are visible in Hotspots`;
                    break;
                case "reportOnly":
                    badgeValue = overloadedModuleCount;
                    badgeTooltip = `${overloadedModuleCount} report-only Overloaded Module candidates are visible in Hotspots`;
                    break;
                default:
                    badgeValue = actionableCount > 0 ? actionableCount : overloadedModuleCount;
                    badgeTooltip =
                        actionableCount > 0
                            ? `${actionableCount} review items need attention`
                            : `${overloadedModuleCount} report-only Overloaded Module candidates are visible in Hotspots`;
                    break;
            }
            this.hotspotsView.badge =
                badgeValue > 0
                    ? {
                        value: badgeValue,
                        tooltip: badgeTooltip,
                    }
                    : undefined;
        }
        if (this.sessionView) {
            this.sessionView.badge = undefined;
            this.sessionView.description =
                state && state.reviewed.length > 0 ? `${state.reviewed.length} reviewed` : undefined;
        }
    }

    updateContextKeys() {
        if (this.disposed) {
            return;
        }
        const state = this.getPrimaryState();
        const activeTarget = this.activeReviewTarget;
        const targetVisibleInEditor = this.isTargetVisibleInEditor(activeTarget);
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.workspaceTrusted",
            vscode.workspace.isTrusted
        );
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.connected",
            this.connectionInfo.connected
        );
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.hasRun",
            Boolean(state && state.latestSummary)
        );
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.runStale",
            Boolean(state && state.stale)
        );
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.hasActiveReviewTarget",
            Boolean(activeTarget)
        );
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.activeReviewTargetVisibleInEditor",
            Boolean(targetVisibleInEditor)
        );
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.activeReviewTargetIsFinding",
            Boolean(activeTarget && activeTarget.nodeType !== "overloadedModule")
        );
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.activeReviewTargetIsReviewed",
            Boolean(activeTarget && activeTarget.reviewed)
        );
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.activeReviewTargetIsOverloadedModule",
            Boolean(activeTarget && activeTarget.nodeType === "overloadedModule")
        );
        void vscode.commands.executeCommand(
            "setContext",
            "codeclone.hotspotFocusMode",
            this.hotspotFocusMode
        );
    }

    updateStatusBar() {
        if (this.disposed) {
            return;
        }
        const showStatusBar = vscode.workspace
            .getConfiguration("codeclone")
            .get("ui.showStatusBar", true);
        if (!showStatusBar) {
            this.statusBar.hide();
            return;
        }
        if (!vscode.workspace.isTrusted) {
            this.statusBar.text = "CodeClone restricted";
            this.statusBar.tooltip =
                "Restricted Mode is active. Grant workspace trust to enable local CodeClone analysis and the local MCP server.";
            this.statusBar.accessibilityInformation = {
                label:
                    "CodeClone restricted. Grant workspace trust to enable local analysis.",
            };
            this.statusBar.command = "codeclone.manageWorkspaceTrust";
            this.statusBar.show();
            return;
        }
        const state = this.getPrimaryState();
        if (!this.connectionInfo.connected) {
            this.statusBar.text = "CodeClone setup";
            this.statusBar.tooltip =
                "CodeClone needs a local MCP launcher. Analyze Workspace usually connects automatically. Use Verify Local Server only when you want to check the launcher manually.";
            this.statusBar.accessibilityInformation = {
                label: "CodeClone setup. Local launcher verification is required.",
            };
            this.statusBar.command = "codeclone.analyzeWorkspace";
            this.statusBar.show();
            return;
        }
        if (!state || !state.latestSummary) {
            this.statusBar.text = "CodeClone ready";
            this.statusBar.tooltip =
                "The local CodeClone server is ready. Start with Analyze Workspace or Review Changes.";
            this.statusBar.accessibilityInformation = {
                label: "CodeClone ready. Start with Analyze Workspace or Review Changes.",
            };
            this.statusBar.command = "codeclone.analyzeWorkspace";
            this.statusBar.show();
            return;
        }
        this.statusBar.text = state.stale
            ? `CodeClone ${state.latestSummary.health.score}/${state.latestSummary.health.grade} · stale`
            : `CodeClone ${state.latestSummary.health.score}/${state.latestSummary.health.grade}`;
        this.statusBar.command = "codeclone.openOverview";
        const drift = this.baselineDrift(state);
        const analysisSettings = this.currentAnalysisSettings(state);
        const pendingAnalysisSettings = this.pendingAnalysisSettings(state);
        const driftLine =
            drift.newFindings !== null || drift.healthDelta !== null || drift.newClones !== null
                ? `\nBaseline drift: ${this.baselineDriftSummary(state)}`
                : "";
        this.statusBar.tooltip =
            `${state.folder.name}\nRun ${state.currentRunId}\n${state.latestSummary.findings.total} findings` +
            (analysisSettings ? `\nAnalysis depth: ${analysisSettings.label}` : "") +
            (pendingAnalysisSettings
                ? `\nNext run: ${pendingAnalysisSettings.label} · pending`
                : "") +
            driftLine +
            (state.stale ? `\nFreshness: stale · ${state.staleReason}` : "");
        this.statusBar.accessibilityInformation = {
            label: state.stale
                ? `CodeClone ${state.latestSummary.health.score} slash ${state.latestSummary.health.grade}, stale.`
                : `CodeClone ${state.latestSummary.health.score} slash ${state.latestSummary.health.grade}.`,
        };
        this.statusBar.show();
    }

    handleError(error, fallbackMessage) {
        const message =
            error instanceof MCPClientError || error instanceof Error
                ? error.message
                : fallbackMessage;
        this.outputChannel.show(true);
        this.outputChannel.appendLine(`[codeclone] error: ${message}`);
        if (this.isCodeCloneSetupError(message)) {
            void this.showSetupGuidance(message);
            return;
        }
        void vscode.window.showErrorMessage(message || fallbackMessage);
    }

    isCodeCloneSetupError(message) {
        const text = String(message || "");
        return (
            text.includes("Failed to start CodeClone MCP") ||
            text.includes("requires the optional 'mcp' extra") ||
            text.includes("requires CodeClone >=") ||
            text.includes("not supported. It reported version") ||
            text.includes("spawn codeclone-mcp ENOENT") ||
            text.includes("spawn uv ENOENT")
        );
    }

    async showSetupGuidance(message) {
        const choice = await vscode.window.showErrorMessage(
            message,
            "Open setup help",
            "Copy install command",
            "Open settings"
        );
        if (choice === "Open setup help") {
            await this.openSetupHelp();
            return;
        }
        if (choice === "Copy install command") {
            await vscode.env.clipboard.writeText(PREVIEW_INSTALL_COMMAND);
            await vscode.window.showInformationMessage(
                "Copied the recommended install command."
            );
            return;
        }
        if (choice === "Open settings") {
            await vscode.commands.executeCommand(
                "workbench.action.openSettings",
                "@ext:orenlab.codeclone codeclone.mcp"
            );
        }
    }
}

let controller = null;

function activate(context) {
    controller = new CodeCloneController(context);
}

async function deactivate() {
    if (controller) {
        const activeController = controller;
        controller = null;
        await activeController.dispose();
        return;
    }
    controller = null;
}

module.exports = {
    activate,
    deactivate,
};
