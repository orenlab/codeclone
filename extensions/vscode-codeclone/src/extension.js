"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vscode = require("vscode");

const { CodeCloneMcpClient, MCPClientError } = require("./mcpClient");

const HELP_TOPICS = [
  "workflow",
  "suppressions",
  "baseline",
  "latest_runs",
  "review_state",
  "changed_scope",
];

const HOTSPOT_GROUPS = [
  { id: "newRegressions", label: "New Regressions", icon: "diff-added" },
  { id: "productionHotspots", label: "Production Hotspots", icon: "target" },
  { id: "changedFiles", label: "Changed Files", icon: "git-commit" },
  { id: "godModules", label: "God Modules", icon: "symbol-module" },
];

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
  return entry.trusted ? `${status} · trusted` : `${status} · untrusted`;
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
    return "No production findings by source kind.";
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

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function safeObject(value) {
  return value && typeof value === "object" ? value : {};
}

function normalizeLocations(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
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
          line:
            typeof entry.line === "number" ? entry.line : null,
          end_line:
            typeof entry.end_line === "number" ? entry.end_line : null,
          symbol: entry.symbol ? String(entry.symbol) : null,
        };
      }
      return null;
    })
    .filter(Boolean);
}

function firstLocation(value) {
  const locations = normalizeLocations(value);
  return locations.length > 0 ? locations[0] : null;
}

function looksLikeCodeCloneRepo(folderPath) {
  return (
    fs.existsSync(path.join(folderPath, "pyproject.toml")) &&
    fs.existsSync(path.join(folderPath, "codeclone", "mcp_server.py"))
  );
}

function markdownBulletList(values) {
  return values.map((value) => `- ${value}`).join("\n");
}

function renderHelpMarkdown(topic, payload) {
  const lines = [
    `# CodeClone MCP Help: ${topic}`,
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
    "## Recommended install for the preview extension",
    "",
    "```bash",
    "pip install --pre \"codeclone[mcp]\"",
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
    "",
    "Once that is ready, run `Analyze Workspace` again.",
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
  const items = safeArray(topHotspots.items);
  const suggestions = safeArray(topSuggestions.items);
  const lines = [
    `# CodeClone Production Triage`,
    "",
    `- Run: \`${state.currentRunId || "n/a"}\``,
    `- Workspace: \`${state.folder.name}\``,
    `- Health: ${health.score || 0}/${health.grade || "?"}`,
    `- Findings: ${findings.total || 0} total · ${findings.production || 0} production`,
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

function renderGodModuleMarkdown(item) {
  const reasons = safeArray(item.candidate_reasons);
  const lines = [
    `# God Module Candidate`,
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

class WorkspaceState {
  constructor(folder) {
    this.folder = folder;
    this.currentRunId = null;
    this.latestSummary = null;
    this.metricsSummary = null;
    this.latestTriage = null;
    this.changedSummary = null;
    this.reviewed = [];
    this.lastScope = "workspace";
    this.lastUpdatedAt = null;
    this.groupCache = new Map();
  }
}

class BaseTreeProvider {
  constructor(controller) {
    this.controller = controller;
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.emitter.event;
  }

  refresh() {
    this.emitter.fire(undefined);
  }

  dispose() {
    this.emitter.dispose();
  }
}

class OverviewTreeProvider extends BaseTreeProvider {
  async getTreeItem(node) {
    return this.controller.createTreeItem(node);
  }

  async getChildren(node) {
    return this.controller.getOverviewChildren(node);
  }
}

class HotspotsTreeProvider extends BaseTreeProvider {
  async getTreeItem(node) {
    return this.controller.createTreeItem(node);
  }

  async getChildren(node) {
    return this.controller.getHotspotsChildren(node);
  }
}

class SessionTreeProvider extends BaseTreeProvider {
  async getTreeItem(node) {
    return this.controller.createTreeItem(node);
  }

  async getChildren(node) {
    return this.controller.getSessionChildren(node);
  }
}

class CodeCloneController {
  constructor(context) {
    this.context = context;
    this.outputChannel = vscode.window.createOutputChannel("CodeClone");
    this.client = new CodeCloneMcpClient(this.outputChannel);
    this.states = new Map();
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
    this.connectionInfo = {
      connected: false,
      serverInfo: null,
      toolCount: 0,
      launchSpec: null,
    };
    this.statusBar = vscode.window.createStatusBarItem(
      "codeclone.status",
      vscode.StatusBarAlignment.Left,
      10
    );
    this.statusBar.command = "codeclone.openOverview";
    this.overviewProvider = new OverviewTreeProvider(this);
    this.hotspotsProvider = new HotspotsTreeProvider(this);
    this.sessionProvider = new SessionTreeProvider(this);
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
    this.client.on("state", (state) => {
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
    });
    this.client.on("exit", async () => {
      await vscode.window.showWarningMessage(
        "The local CodeClone server disconnected. Run Analyze Workspace to reconnect and refresh the current workspace."
      );
    });
    context.subscriptions.push(
      this.outputChannel,
      this.statusBar,
      this.revealDecoration,
      this.overviewProvider,
      this.hotspotsProvider,
      this.sessionProvider,
      this.overviewView,
      this.hotspotsView,
      this.sessionView,
      {
        dispose: () => {
          void this.client.dispose();
        },
      }
    );
    this.registerCommands();
    this.updateContextKeys();
    this.updateStatusBar();
    this.updateViewChrome();
  }

  registerCommands() {
    const subscriptions = [
      vscode.commands.registerCommand("codeclone.connectMcp", () =>
        this.connectMcp()
      ),
      vscode.commands.registerCommand("codeclone.analyzeWorkspace", (arg) =>
        this.analyzeWorkspace(arg)
      ),
      vscode.commands.registerCommand("codeclone.analyzeChangedFiles", (arg) =>
        this.analyzeChangedFiles(arg)
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
      vscode.commands.registerCommand("codeclone.reviewFinding", (node) =>
        this.reviewFinding(node)
      ),
      vscode.commands.registerCommand("codeclone.openFinding", (node) =>
        this.openFinding(node)
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
      vscode.commands.registerCommand("codeclone.openGodModule", (node) =>
        this.openGodModule(node)
      ),
      vscode.commands.registerCommand("codeclone.reviewGodModule", (node) =>
        this.reviewGodModule(node)
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

  async pickWorkspaceFolder(placeHolder) {
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

  resolveLaunchSpec(folder) {
    const config = vscode.workspace.getConfiguration("codeclone", folder.uri);
    const configuredCommand = config.get("mcp.command", "auto");
    const configuredArgs = config.get("mcp.args", []);
    if (configuredCommand && configuredCommand !== "auto") {
      return {
        command: configuredCommand,
        args: Array.isArray(configuredArgs) ? configuredArgs : [],
        cwd: folder.uri.fsPath,
      };
    }
    return {
      command: "codeclone-mcp",
      args: Array.isArray(configuredArgs) ? configuredArgs : [],
      cwd: folder.uri.fsPath,
      fallback: looksLikeCodeCloneRepo(folder.uri.fsPath)
        ? {
            command: "uv",
            args: ["run", "codeclone-mcp"],
            cwd: folder.uri.fsPath,
          }
        : null,
    };
  }

  async ensureConnected(folder) {
    const launchSpec = this.resolveLaunchSpec(folder);
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

  async refreshCurrentRun() {
    const state = this.getPrimaryState();
    if (!state) {
      await this.analyzeWorkspace();
      return;
    }
    await this.runAnalysis(state.folder, state.lastScope === "changed");
  }

  async runAnalysis(folder, changedMode) {
    const state = this.getWorkspaceState(folder);
    const config = vscode.workspace.getConfiguration("codeclone", folder.uri);
    const cachePolicy = config.get("analysis.cachePolicy", "reuse");
    const diffRef = config.get("analysis.changedDiffRef", "HEAD");
    const title = changedMode
      ? `CodeClone: Analyzing changed files in ${folder.name}`
      : `CodeClone: Analyzing ${folder.name}`;
    const previousText = this.statusBar.text;
    this.statusBar.text = "$(loading~spin) CodeClone analyzing";
    this.statusBar.show();
    try {
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title,
        },
        async () => {
          await this.ensureConnected(folder);
          const analysisPayload = changedMode
            ? await this.client.callTool("analyze_changed_paths", {
                root: folder.uri.fsPath,
                git_diff_ref: diffRef,
                cache_policy: cachePolicy,
              })
            : await this.client.callTool("analyze_repository", {
                root: folder.uri.fsPath,
                cache_policy: cachePolicy,
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
          state.currentRunId = runId;
          state.latestSummary = summary;
          state.latestTriage = triage;
          state.metricsSummary = metrics.summary || metrics;
          state.changedSummary = changedMode ? analysisPayload : null;
          state.reviewed = safeArray(reviewed.items);
          state.lastScope = changedMode ? "changed" : "workspace";
          state.lastUpdatedAt = new Date();
          state.groupCache.clear();
        }
      );
      this.updateContextKeys();
      this.updateStatusBar();
      this.refreshAllViews();
      await this.openOverview();
    } catch (error) {
      this.handleError(error, "CodeClone analysis failed.");
    } finally {
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
        "Run Analyze Workspace first to open production triage."
      );
      return;
    }
    await this.showMarkdownDocument(renderTriageMarkdown(state));
  }

  async reviewPriorityQueue() {
    const state = this.getPrimaryState();
    if (!state || !state.currentRunId) {
      await vscode.window.showInformationMessage(
        "Run Analyze Workspace first to review CodeClone priorities."
      );
      return;
    }
    try {
      await this.ensureConnected(state.folder);
      const queue = await this.getPriorityQueueNodes(state);
      if (queue.length === 0) {
        await vscode.window.showInformationMessage(
          "No new or production hotspots need review in the current run."
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
          placeHolder: "Select the next CodeClone hotspot to review",
          matchOnDetail: true,
        }
      );
      if (picked) {
        await this.reviewFinding(picked.node);
      }
    } catch (error) {
      this.handleError(error, "Could not load the CodeClone review queue.");
    }
  }

  async reviewFinding(node) {
    if (!node || !node.findingId || !node.runId) {
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
          label: "Mark as reviewed",
          description: "Hide from review-focused lists",
          action: "reviewed",
        },
      ],
      {
        placeHolder: `What do you want to do with ${node.findingId}?`,
      }
    );
    if (!picked) {
      return;
    }
    if (picked.action === "reveal") {
      await this.revealFindingSource(node);
      return;
    }
    if (picked.action === "detail") {
      await this.openFinding(node);
      return;
    }
    if (picked.action === "remediation") {
      await this.showRemediation(node);
      return;
    }
    if (picked.action === "reviewed") {
      await this.markFindingReviewed(node);
    }
  }

  async openFinding(node) {
    if (!node || !node.findingId || !node.runId) {
      return;
    }
    const state = this.states.get(node.workspaceKey);
    if (!state) {
      return;
    }
    try {
      await this.ensureConnected(state.folder);
      const payload = await this.client.callTool("get_finding", {
        run_id: node.runId,
        finding_id: node.findingId,
        detail_level: "normal",
      });
      await this.showMarkdownDocument(renderFindingMarkdown(payload));
    } catch (error) {
      this.handleError(error, `Could not open finding ${node.findingId}.`);
    }
  }

  async showRemediation(node) {
    if (!node || !node.findingId || !node.runId) {
      return;
    }
    const state = this.states.get(node.workspaceKey);
    if (!state) {
      return;
    }
    try {
      await this.ensureConnected(state.folder);
      const payload = await this.client.callTool("get_remediation", {
        run_id: node.runId,
        finding_id: node.findingId,
        detail_level: "normal",
      });
      await this.showMarkdownDocument(renderRemediationMarkdown(payload));
    } catch (error) {
      this.handleError(error, `Could not load remediation for ${node.findingId}.`);
    }
  }

  async markFindingReviewed(node) {
    if (!node || !node.findingId || !node.runId) {
      return;
    }
    const state = this.states.get(node.workspaceKey);
    if (!state) {
      return;
    }
    try {
      await this.ensureConnected(state.folder);
      await this.client.callTool("mark_finding_reviewed", {
        run_id: node.runId,
        finding_id: node.findingId,
      });
      const reviewed = await this.client.callTool("list_reviewed_findings", {
        run_id: node.runId,
      });
      state.reviewed = safeArray(reviewed.items);
      this.sessionProvider.refresh();
      await vscode.window.showInformationMessage(
        `Marked ${node.findingId} as reviewed.`
      );
    } catch (error) {
      this.handleError(error, `Could not mark ${node.findingId} as reviewed.`);
    }
  }

  async copyFindingId(node) {
    if (!node || !node.findingId) {
      return;
    }
    await vscode.env.clipboard.writeText(String(node.findingId));
    await vscode.window.showInformationMessage(
      `Copied finding id: ${node.findingId}`
    );
  }

  async revealFindingSource(node) {
    if (!node) {
      return;
    }
    const state = this.states.get(node.workspaceKey);
    if (!state) {
      return;
    }
    let location = firstLocation(node.locations);
    if (!location && node.findingId && node.runId) {
      try {
        await this.ensureConnected(state.folder);
        const payload = await this.client.callTool("get_finding", {
          run_id: node.runId,
          finding_id: node.findingId,
          detail_level: "normal",
        });
        location = firstLocation(payload.locations);
      } catch (error) {
        this.handleError(error, "Could not resolve finding location.");
        return;
      }
    }
    if (!location || !location.path) {
      await vscode.window.showInformationMessage(
        "This item does not expose a source location."
      );
      return;
    }
    await this.revealWorkspacePath(
      state.folder,
      location.path,
      location.line,
      location.end_line
    );
  }

  async revealWorkspacePath(folder, relativePath, line = null, endLine = null) {
    const fileUri = vscode.Uri.file(path.join(folder.uri.fsPath, relativePath));
    try {
      const document = await vscode.workspace.openTextDocument(fileUri);
      const editor = await vscode.window.showTextDocument(document, {
        preview: true,
      });
      if (typeof line === "number") {
        const startLine = Math.max(line - 1, 0);
        const finalLine = Math.max(
          typeof endLine === "number" ? endLine - 1 : startLine,
          startLine
        );
        const position = new vscode.Position(startLine, 0);
        const endPosition = new vscode.Position(
          finalLine,
          document.lineAt(finalLine).range.end.character
        );
        const range = new vscode.Range(position, endPosition);
        editor.selection = new vscode.Selection(position, position);
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

  async openGodModule(node) {
    if (!node || !node.item) {
      return;
    }
    await this.showMarkdownDocument(renderGodModuleMarkdown(node.item));
  }

  async reviewGodModule(node) {
    if (!node || !node.item || !node.workspaceKey) {
      return;
    }
    const picked = await vscode.window.showQuickPick(
      [
        {
          label: "Reveal module source",
          description: "Recommended",
          action: "reveal",
        },
        {
          label: "Show report-only detail",
          description: "Open God Module summary",
          action: "detail",
        },
      ],
      {
        placeHolder: `What do you want to do with ${node.item.path}?`,
      }
    );
    if (!picked) {
      return;
    }
    if (picked.action === "reveal") {
      const state = this.states.get(node.workspaceKey);
      if (!state) {
        return;
      }
      await this.revealWorkspacePath(state.folder, node.item.path);
      return;
    }
    await this.openGodModule(node);
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
        state.reviewed = [];
        state.groupCache.clear();
      }
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
        label: topic,
        description: "CodeClone MCP help topic",
      })),
      {
        placeHolder: "Select a CodeClone MCP help topic",
      }
    );
    return picked ? picked.label : null;
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

  async getOverviewChildren(node) {
    const state = this.getPrimaryState();
    if (!state || !state.latestSummary) {
      return [];
    }
    if (!node) {
      const sections = [
        {
          nodeType: "section",
          id: "overview.health",
          label: "Structural Health",
          description: `${state.latestSummary.health.score}/${state.latestSummary.health.grade}`,
          icon: new vscode.ThemeIcon("heart"),
        },
        {
          nodeType: "section",
          id: "overview.run",
          label: "Current Run",
          description: `${state.currentRunId} · ${state.latestSummary.cache.freshness}`,
          icon: new vscode.ThemeIcon("pulse"),
        },
        {
          nodeType: "section",
          id: "overview.triage",
          label: "Priority Review",
          description: `${state.latestSummary.findings.production} production · ${state.latestSummary.findings.new} new`,
          icon: new vscode.ThemeIcon("inspect"),
          command: {
            command: "codeclone.openProductionTriage",
            title: "Open Production Triage",
          },
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
      if (safeObject(state.metricsSummary).god_modules) {
        const godModules = safeObject(state.metricsSummary).god_modules;
        sections.push({
          nodeType: "section",
          id: "overview.god",
          label: "God Modules",
          description: `${godModules.candidates} candidates · top ${decimal(godModules.top_score)} (report-only)`,
          icon: new vscode.ThemeIcon("symbol-module"),
        });
      }
      return sections;
    }
    if (node.id === "overview.health") {
      const dimensions = safeObject(state.latestSummary.health.dimensions);
      return [
        this.detailNode("Score", `${state.latestSummary.health.score}/${state.latestSummary.health.grade}`),
        this.detailNode("Clones", number(dimensions.clones)),
        this.detailNode("Complexity", number(dimensions.complexity)),
        this.detailNode("Coupling", number(dimensions.coupling)),
        this.detailNode("Cohesion", number(dimensions.cohesion)),
        this.detailNode("Dead code", number(dimensions.dead_code)),
        this.detailNode("Dependencies", number(dimensions.dependencies)),
        this.detailNode("Coverage", number(dimensions.coverage)),
      ];
    }
    if (node.id === "overview.run") {
      const inventory = safeObject(state.latestSummary.inventory);
      return [
        this.detailNode("Workspace", state.folder.name),
        this.detailNode("Run id", state.currentRunId),
        this.detailNode("Files", number(inventory.files)),
        this.detailNode("Parsed lines", number(inventory.lines)),
        this.detailNode("Callables", number(inventory.functions)),
        this.detailNode("Classes", number(inventory.classes)),
        this.detailNode("Baseline", formatBaselineState(state.latestSummary.baseline)),
        this.detailNode(
          "Metrics baseline",
          formatBaselineState(state.latestSummary.metrics_baseline)
        ),
        this.detailNode("Cache", formatCacheSummary(state.latestSummary.cache)),
      ];
    }
    if (node.id === "overview.triage") {
      const triage = safeObject(state.latestTriage);
      const findings = safeObject(triage.findings);
      const nextAction = this.describeNextBestAction(state);
      return [
        this.detailNode("Next best action", nextAction.label, {
          command: nextAction.command,
          title: nextAction.title,
        }),
        this.detailNode("New regressions", number(state.latestSummary.findings.new)),
        this.detailNode("Production hotspots", number(state.latestSummary.findings.production)),
        this.detailNode("Outside focus", number(findings.outside_focus)),
        this.detailNode(
          "Changed files",
          state.changedSummary
            ? `${number(state.changedSummary.changed_files)} · ${state.changedSummary.verdict}`
            : "not analyzed"
        ),
      ];
    }
    if (node.id === "overview.changed") {
      return [
        this.detailNode("Changed files", number(state.changedSummary.changed_files)),
        this.detailNode("Verdict", String(state.changedSummary.verdict)),
        this.detailNode("New findings", number(state.changedSummary.new_findings)),
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
      const godModules = safeObject(state.metricsSummary).god_modules;
      return [
        this.detailNode("Candidates", number(godModules.candidates)),
        this.detailNode("Ranked modules", number(godModules.total)),
        this.detailNode("Top score", decimal(godModules.top_score)),
        this.detailNode("Average score", decimal(godModules.average_score)),
        this.detailNode("Population", String(godModules.population_status)),
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
      const groups = HOTSPOT_GROUPS.filter((group) =>
        this.shouldShowGroup(group.id, state)
      );
      if (groups.length === 0) {
        return [
          {
            nodeType: "message",
            label: "No new or production hotspots need review in the current run.",
            icon: new vscode.ThemeIcon("circle-slash"),
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
          description: this.connectionInfo.connected ? "ready" : "unavailable",
          icon: new vscode.ThemeIcon("plug"),
        },
        {
          nodeType: "section",
          id: "session.run",
          label: "Current Run",
          description: state && state.currentRunId ? state.currentRunId : "none",
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
          "Server version",
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
        return [this.detailNode("Run", "No run available yet.")];
      }
      return [
        this.detailNode("Workspace", state.folder.name),
        this.detailNode("Run id", state.currentRunId),
        this.detailNode("Scope", formatRunScope(state.lastScope)),
        this.detailNode("Mode", state.latestSummary.mode),
        this.detailNode("Cache freshness", state.latestSummary.cache.freshness),
        this.detailNode("Updated", state.lastUpdatedAt ? state.lastUpdatedAt.toLocaleString() : "unknown"),
      ];
    }
    if (node.id === "session.reviewed") {
      if (!state || !state.currentRunId || state.reviewed.length === 0) {
        return [
          {
            nodeType: "message",
            label: "No reviewed findings in this MCP session.",
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
      const runId = state.currentRunId;
      if (!runId) {
        return [];
      }
      let nodes;
      switch (groupId) {
        case "newRegressions":
          nodes = this.toFindingNodes(
            state,
            safeArray(
              (
                await this.client.callTool("list_findings", {
                  run_id: runId,
                  novelty: "new",
                  detail_level: "summary",
                  sort_by: "priority",
                  limit: 20,
                  exclude_reviewed: true,
                })
              ).items
            )
          );
          break;
        case "productionHotspots":
          nodes = this.toFindingNodes(
            state,
            safeArray(
              (
                await this.client.callTool("list_hotspots", {
                  run_id: runId,
                  kind: "production_hotspots",
                  detail_level: "summary",
                  limit: 10,
                  exclude_reviewed: true,
                })
              ).items
            )
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
            safeArray(
              (
                await this.client.callTool("list_findings", {
                  run_id: runId,
                  git_diff_ref: vscode.workspace
                    .getConfiguration("codeclone", state.folder.uri)
                    .get("analysis.changedDiffRef", "HEAD"),
                  novelty: "new",
                  detail_level: "summary",
                  sort_by: "priority",
                  limit: 20,
                  exclude_reviewed: true,
                })
              ).items
            )
          );
          break;
        case "godModules": {
          const response = await this.client.callTool("get_report_section", {
            run_id: runId,
            section: "metrics_detail",
            family: "god_modules",
            limit: 15,
          });
          nodes = safeArray(response.items).map((item) => ({
            nodeType: "godModule",
            workspaceKey: state.folder.uri.toString(),
            runId,
            item,
            label: item.path,
            description: `${decimal(item.score)} · ${item.source_kind}`,
            tooltip: `${item.module} · ${number(item.loc)} LOC · ${item.total_deps} deps`,
            icon: new vscode.ThemeIcon("symbol-module"),
            command: {
              command: "codeclone.reviewGodModule",
              title: "Review God Module",
              arguments: [{ workspaceKey: state.folder.uri.toString(), runId, item }],
            },
          }));
          break;
        }
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

  async getPriorityQueueNodes(state) {
    const runId = state.currentRunId;
    if (!runId) {
      return [];
    }
    const diffRef = vscode.workspace
      .getConfiguration("codeclone", state.folder.uri)
      .get("analysis.changedDiffRef", "HEAD");
    const buckets = [];
    if (state.changedSummary) {
      buckets.push(
        safeArray(
          (
            await this.client.callTool("list_findings", {
              run_id: runId,
              git_diff_ref: diffRef,
              novelty: "new",
              detail_level: "summary",
              sort_by: "priority",
              limit: 12,
              exclude_reviewed: true,
            })
          ).items
        )
      );
    }
    buckets.push(
      safeArray(
        (
          await this.client.callTool("list_hotspots", {
            run_id: runId,
            kind: "production_hotspots",
            detail_level: "summary",
            limit: 12,
            exclude_reviewed: true,
          })
        ).items
      )
    );
    buckets.push(
      safeArray(
        (
          await this.client.callTool("list_findings", {
            run_id: runId,
            novelty: "new",
            detail_level: "summary",
            sort_by: "priority",
            limit: 12,
            exclude_reviewed: true,
          })
        ).items
      )
    );
    const deduped = [];
    const seen = new Set();
    for (const bucket of buckets) {
      for (const item of bucket) {
        const id = String(item.id || "");
        if (!id || seen.has(id)) {
          continue;
        }
        seen.add(id);
        deduped.push(item);
      }
    }
    return this.toFindingNodes(state, deduped);
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
      contextValue: "codeclone.finding",
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
    const summary = safeObject(state.latestSummary);
    const findings = safeObject(summary.findings);
    const metrics = safeObject(state.metricsSummary);
    switch (groupId) {
      case "newRegressions":
        return `${findings.new || 0} new`;
      case "productionHotspots":
        return `${safeObject(state.latestTriage).top_hotspots?.available || 0} prod`;
      case "changedFiles":
        return state.changedSummary
          ? `${state.changedSummary.new_findings} new · ${state.changedSummary.verdict}`
          : "not analyzed";
      case "godModules":
        return `${safeObject(metrics.god_modules).candidates || 0} report-only`;
      default:
        return "";
    }
  }

  emptyGroupMessage(groupId) {
    switch (groupId) {
      case "newRegressions":
        return "No new regressions in the current run.";
      case "productionHotspots":
        return "No production hotspots need review.";
      case "changedFiles":
        return "No new findings touch the changed files.";
      case "godModules":
        return "No report-only God Module candidates are visible.";
      default:
        return "No items in this category.";
    }
  }

  shouldShowGroup(groupId, state) {
    const summary = safeObject(state.latestSummary);
    const findings = safeObject(summary.findings);
    const metrics = safeObject(state.metricsSummary);
    switch (groupId) {
      case "newRegressions":
        return Number(findings.new || 0) > 0;
      case "productionHotspots":
        return Number(safeObject(state.latestTriage).top_hotspots?.available || 0) > 0;
      case "changedFiles":
        return Boolean(state.changedSummary);
      case "godModules":
        return Number(safeObject(metrics.god_modules).candidates || 0) > 0;
      default:
        return false;
    }
  }

  describeNextBestAction(state) {
    if (Number(state.latestSummary.findings.new || 0) > 0) {
      return {
        label: "Review new regressions",
        command: "codeclone.reviewPriorityQueue",
        title: "Review new regressions",
      };
    }
    if (Number(state.latestSummary.findings.production || 0) > 0) {
      return {
        label: "Review production hotspots",
        command: "codeclone.reviewPriorityQueue",
        title: "Review production hotspots",
      };
    }
    if (state.changedSummary) {
      return {
        label: "Inspect changed-files review",
        command: "codeclone.focusHotspots",
        title: "Inspect changed-files review",
      };
    }
    if (Number(safeObject(state.metricsSummary).god_modules?.candidates || 0) > 0) {
      return {
        label: "Inspect report-only God Modules",
        command: "codeclone.focusHotspots",
        title: "Inspect report-only God Modules",
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
    switch (node.nodeType) {
      case "section": {
        const item = new vscode.TreeItem(
          node.label,
          vscode.TreeItemCollapsibleState.Expanded
        );
        item.id = node.id;
        item.description = node.description;
        item.iconPath = node.icon;
        item.command = node.command;
        return item;
      }
      case "group": {
        const item = new vscode.TreeItem(
          node.label,
          vscode.TreeItemCollapsibleState.Collapsed
        );
        item.id = `${node.workspaceKey}:${node.groupId}`;
        item.description = node.description;
        item.iconPath = node.icon;
        return item;
      }
      case "finding": {
        const item = new vscode.TreeItem(
          node.label,
          vscode.TreeItemCollapsibleState.None
        );
        item.description = node.description;
        item.tooltip = node.tooltip;
        item.iconPath = node.icon;
        item.contextValue = "codeclone.finding";
        item.command = node.command;
        return item;
      }
      case "godModule": {
        const item = new vscode.TreeItem(
          node.label,
          vscode.TreeItemCollapsibleState.None
        );
        item.description = node.description;
        item.tooltip = node.tooltip;
        item.iconPath = node.icon;
        item.contextValue = "codeclone.godModule";
        item.command = node.command;
        return item;
      }
      case "helpTopic": {
        const item = new vscode.TreeItem(
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
        return item;
      }
      case "detail": {
        const item = new vscode.TreeItem(
          node.label,
          vscode.TreeItemCollapsibleState.None
        );
        item.description = node.description;
        item.iconPath = node.icon;
        item.command = node.command;
        return item;
      }
      case "message":
      default: {
        const item = new vscode.TreeItem(
          node.label,
          vscode.TreeItemCollapsibleState.None
        );
        item.iconPath = node.icon || new vscode.ThemeIcon("info");
        item.description = node.description;
        return item;
      }
    }
  }

  refreshAllViews() {
    this.overviewProvider.refresh();
    this.hotspotsProvider.refresh();
    this.sessionProvider.refresh();
    this.updateViewChrome();
  }

  updateViewChrome() {
    const state = this.getPrimaryState();
    if (this.overviewView) {
      this.overviewView.badge = undefined;
    }
    if (this.hotspotsView) {
      const newCount = Number(
        safeObject(state?.latestSummary).findings?.new || 0
      );
      const productionCount = Number(
        safeObject(state?.latestSummary).findings?.production || 0
      );
      const changedCount = Number(state?.changedSummary?.new_findings || 0);
      const actionableCount = Math.max(newCount + productionCount, changedCount);
      const godModuleCount = Number(
        safeObject(state?.metricsSummary).god_modules?.candidates || 0
      );
      this.hotspotsView.badge =
        actionableCount > 0
          ? {
              value: actionableCount,
              tooltip: `${actionableCount} review items need attention`,
            }
          : godModuleCount > 0
            ? {
                value: godModuleCount,
                tooltip: `${godModuleCount} report-only God Module candidates are visible in Hotspots`,
              }
            : undefined;
    }
    if (this.sessionView) {
      this.sessionView.badge = undefined;
    }
  }

  updateContextKeys() {
    const state = this.getPrimaryState();
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
  }

  updateStatusBar() {
    const showStatusBar = vscode.workspace
      .getConfiguration("codeclone")
      .get("ui.showStatusBar", true);
    if (!showStatusBar) {
      this.statusBar.hide();
      return;
    }
    const state = this.getPrimaryState();
    if (!this.connectionInfo.connected) {
      this.statusBar.text = "CodeClone setup";
      this.statusBar.tooltip =
        "Run Analyze Workspace to start CodeClone and create the first run. Use Verify Local Server only if you want to check the launcher manually.";
      this.statusBar.command = "codeclone.analyzeWorkspace";
      this.statusBar.show();
      return;
    }
    if (!state || !state.latestSummary) {
      this.statusBar.text = "CodeClone ready";
      this.statusBar.tooltip =
        "The local CodeClone server is ready. Run Analyze Workspace or Review Changes.";
      this.statusBar.command = "codeclone.analyzeWorkspace";
      this.statusBar.show();
      return;
    }
    this.statusBar.text = `CodeClone ${state.latestSummary.health.score}/${state.latestSummary.health.grade}`;
    this.statusBar.command = "codeclone.openOverview";
    this.statusBar.tooltip =
      `${state.folder.name}\nRun ${state.currentRunId}\n${state.latestSummary.findings.total} findings`;
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
      await vscode.env.clipboard.writeText('pip install --pre "codeclone[mcp]"');
      await vscode.window.showInformationMessage(
        'Copied: pip install --pre "codeclone[mcp]"'
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
    await controller.client.dispose();
  }
}

module.exports = {
  activate,
  deactivate,
};
