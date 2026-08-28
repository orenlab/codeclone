package io.orenlab.codeclone.jetbrains.service

import com.intellij.notification.Notification
import com.intellij.notification.NotificationType
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.LocalFileSystem
import io.orenlab.codeclone.jetbrains.analysis.AnalysisSettingsResolver
import io.orenlab.codeclone.jetbrains.analysis.CoverageXmlResolver
import io.orenlab.codeclone.jetbrains.mcp.McpClient
import io.orenlab.codeclone.jetbrains.mcp.McpClientException
import io.orenlab.codeclone.jetbrains.mcp.McpLauncher
import io.orenlab.codeclone.jetbrains.memory.MemoryGovernance
import io.orenlab.codeclone.jetbrains.memory.MemorySnapshotLoader
import io.orenlab.codeclone.jetbrains.settings.CodeCloneSettings
import io.orenlab.codeclone.jetbrains.ui.NavigationHelper
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.File
import java.nio.file.Path
import java.util.concurrent.CopyOnWriteArrayList

@Service(Service.Level.PROJECT)
class CodeCloneProjectService(private val project: Project) : Disposable {
    private val LOG = Logger.getInstance(CodeCloneProjectService::class.java)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val client = McpClient()
    private val connectMutex = Mutex()
    private val listeners = CopyOnWriteArrayList<() -> Unit>()

    private val _state = MutableStateFlow(WorkspaceRunState())
    val state: StateFlow<WorkspaceRunState> = _state

    private var busy = false

    fun addListener(listener: () -> Unit): Disposable {
        listeners.add(listener)
        return Disposable { listeners.remove(listener) }
    }

    fun onProjectOpened() {
        project.basePath?.let { LocalFileSystem.getInstance().refreshIoFiles(listOf(File(it))) }
    }

    fun workspaceRoot(): Path {
        val base = project.basePath ?: throw McpClientException("Project has no base path.")
        return Path.of(base)
    }

    fun absoluteRoot(): String = workspaceRoot().toString()

    suspend fun ensureConnected() {
        connectMutex.withLock {
            if (client.isConnected()) return
            val settings = CodeCloneSettings.getInstance()
            val plan = McpLauncher.resolve(
                workspaceRoot = workspaceRoot(),
                configuredCommand = settings.config.mcpCommand,
                configuredArgs = settings.mcpArgsList(),
            )
            connectWithFallback(plan)
            MemoryGovernance.ensureIdeGovernanceRegistered(client, absoluteRoot())
            updateConnectionSummary()
            notify(
                "Connected to CodeClone MCP (${client.snapshot().serverVersion ?: "unknown"}) " +
                    "via ${client.snapshot().launchSpec?.source ?: "unknown"}",
                NotificationType.INFORMATION,
            )
        }
    }

    private suspend fun connectWithFallback(plan: io.orenlab.codeclone.jetbrains.mcp.McpLaunchPlan) {
        try {
            client.connect(plan.primary)
        } catch (primaryError: Exception) {
            val fallback = plan.fallback
            if (fallback == null) {
                throw primaryError
            }
            LOG.warn(
                "Primary CodeClone MCP launch failed (${plan.primary.source}); trying ${fallback.source}",
                primaryError,
            )
            client.connect(fallback)
        }
    }

    fun connectAsync(onDone: (Throwable?) -> Unit = {}) {
        scope.launch {
            runCatching { ensureConnected() }
                .onSuccess {
                    refreshWorkspaceContextAsync(onDone)
                }
                .onFailure { error ->
                    LOG.warn("CodeClone connect failed", error)
                    notify(error.message ?: "Connect failed", NotificationType.ERROR)
                    onDone(error)
                }
            fireChanged()
        }
    }

    fun analyzeWorkspaceAsync(onDone: (Throwable?) -> Unit = {}) = analyzeAsync(AnalysisScope.FULL, onDone)

    fun analyzeChangedFilesAsync(onDone: (Throwable?) -> Unit = {}) = analyzeAsync(AnalysisScope.CHANGED, onDone)

    fun refreshRunAsync(onDone: (Throwable?) -> Unit = {}) {
        val last = _state.value.lastScope
        analyzeAsync(if (last == "changed") AnalysisScope.CHANGED else AnalysisScope.FULL, onDone)
    }

    fun refreshMemoryAsync(onDone: (Throwable?) -> Unit = {}) = refreshWorkspaceContextAsync(onDone)

    private fun refreshWorkspaceContextAsync(onDone: (Throwable?) -> Unit = {}) {
        scope.launch {
            runCatching {
                ensureConnected()
                val root = absoluteRoot()
                _state.value = _state.value.copy(
                    memory = MemorySnapshotLoader.load(client, root),
                    sessionInsights = SessionInsightsLoader.loadSummary(client, root),
                )
            }.onFailure { error ->
                LOG.warn("CodeClone workspace context refresh failed", error)
                notify(error.message ?: "Refresh failed", NotificationType.ERROR)
                onDone(error)
            }.onSuccess {
                onDone(null)
            }
            fireChanged()
        }
    }

    fun clearSessionAsync(onDone: (Throwable?) -> Unit = {}) {
        scope.launch {
            runCatching {
                ensureConnected()
                client.callTool("clear_session_runs", buildJsonObject { put("root", absoluteRoot()) })
            }.onFailure { error ->
                notify(error.message ?: "Clear session failed", NotificationType.ERROR)
                onDone(error)
            }.onSuccess {
                onDone(null)
                fireChanged()
            }
        }
    }

    fun openProductionTriage() {
        scope.launch {
            runCatching {
                ensureConnected()
                if (_state.value.runId == null) {
                    throw McpClientException("Run workspace analysis before opening production triage.")
                }
                if (_state.value.triage == null) {
                    val triage = client.callTool(
                        "get_production_triage",
                        buildJsonObject { put("root", absoluteRoot()) },
                    ).jsonObject
                    _state.value = _state.value.copy(triage = triage)
                    fireChanged()
                }
                ApplicationManager.getApplication().invokeLater {
                    io.orenlab.codeclone.jetbrains.toolwindow.CodeCloneToolWindowPanels
                        .getInstance(project)
                        .showProductionTriage()
                }
            }.onFailure { error ->
                notify(error.message ?: "Triage failed", NotificationType.ERROR)
            }
        }
    }

    fun revealFinding(item: FindingItem) {
        NavigationHelper.openFinding(project, workspaceRoot(), item)
    }

    fun showRemediation(item: FindingItem) {
        scope.launch {
            runCatching {
                ensureConnected()
                val remediation = client.callTool(
                    "get_remediation",
                    buildJsonObject {
                        put("root", absoluteRoot())
                        put("finding_id", item.id)
                    },
                ).jsonObject
                val markdown = WorkspaceInsightsFormatter.formatRemediationMarkdown(remediation)
                openScratch("CodeClone Remediation", markdown)
            }.onFailure { error ->
                notify(error.message ?: "Remediation failed", NotificationType.ERROR)
            }
        }
    }

    fun openMemoryRecord(recordId: String) {
        scope.launch {
            runCatching {
                ensureConnected()
                val response = client.callTool(
                    "query_engineering_memory",
                    buildJsonObject {
                        put("root", absoluteRoot())
                        put("mode", "get")
                        put("record_id", recordId)
                    },
                ).jsonObject
                val payload = response["payload"]?.jsonObject
                val record = payload?.get("record")?.jsonObject ?: payload
                val text = buildString {
                    appendLine("# Engineering Memory Record")
                    appendLine()
                    appendLine("ID: ${record?.get("id")?.jsonPrimitive?.content ?: recordId}")
                    appendLine("Type: ${record?.get("type")?.jsonPrimitive?.content ?: "—"}")
                    appendLine("Status: ${record?.get("status")?.jsonPrimitive?.content ?: "—"}")
                    appendLine("Confidence: ${record?.get("confidence")?.jsonPrimitive?.content ?: "—"}")
                    appendLine()
                    appendLine(record?.get("statement")?.jsonPrimitive?.content ?: "No statement available.")
                }
                openScratch("CodeClone Memory", text)
            }.onFailure { error ->
                notify(error.message ?: "Could not open memory record", NotificationType.ERROR)
            }
        }
    }

    fun markFindingReviewed(item: FindingItem) {
        scope.launch {
            runCatching {
                ensureConnected()
                val runId = _state.value.runId ?: throw McpClientException("No active run to mark reviewed.")
                client.callTool(
                    "mark_finding_reviewed",
                    buildJsonObject {
                        put("run_id", runId)
                        put("finding_id", item.id)
                    },
                )
                val reviewed = client.callTool(
                    "list_reviewed_findings",
                    buildJsonObject { put("run_id", runId) },
                ).jsonObject
                _state.value = _state.value.copy(
                    reviewedFindingIds = RunArtifactsLoader.parseReviewedFindingIds(reviewed),
                )
            }.onFailure { error ->
                notify(error.message ?: "Could not mark finding reviewed", NotificationType.ERROR)
            }.onSuccess {
                notify("Marked ${item.id} as reviewed.", NotificationType.INFORMATION)
                fireChanged()
            }
        }
    }

    fun openSessionStats() {
        scope.launch {
            runCatching {
                ensureConnected()
                if (!client.hasTool("get_workspace_session_stats")) {
                    throw McpClientException("Session stats require CodeClone MCP with IDE governance channel.")
                }
                val payload = client.callTool(
                    "get_workspace_session_stats",
                    buildJsonObject { put("root", absoluteRoot()) },
                ).jsonObject
                val markdown = WorkspaceInsightsFormatter.formatSessionStatsMarkdown(
                    payload,
                    project.name,
                )
                openScratch("CodeClone Session Stats", markdown)
            }.onFailure { error ->
                notify(error.message ?: "Session stats failed", NotificationType.ERROR)
            }
        }
    }

    fun openSessionStatsInPanel(onHtml: (String) -> Unit) = loadSessionStatsHtml(onHtml)

    fun openAuditTrailInPanel(onHtml: (String) -> Unit) = loadAuditTrailHtml(onHtml)

    fun loadSessionStatsHtml(onHtml: (String) -> Unit) {
        scope.launch {
            runCatching {
                ensureConnected()
                if (!client.hasTool("get_workspace_session_stats")) {
                    throw McpClientException("Session stats require CodeClone MCP with IDE governance channel.")
                }
                val payload = client.callTool(
                    "get_workspace_session_stats",
                    buildJsonObject { put("root", absoluteRoot()) },
                ).jsonObject
                val html = io.orenlab.codeclone.jetbrains.ui.render.WorkspaceInsightsHtmlRenderer
                    .renderSessionStatsHtml(payload, project.name)
                ApplicationManager.getApplication().invokeLater { onHtml(html) }
            }.onFailure { error ->
                notify(error.message ?: "Session stats failed", NotificationType.ERROR)
            }
        }
    }

    fun loadAuditTrailHtml(onHtml: (String) -> Unit) {
        scope.launch {
            runCatching {
                ensureConnected()
                if (!client.hasTool("get_controller_audit_trail")) {
                    throw McpClientException("Audit trail requires CodeClone MCP with IDE governance channel.")
                }
                val payload = client.callTool(
                    "get_controller_audit_trail",
                    buildJsonObject {
                        put("root", absoluteRoot())
                        put("limit", 50)
                    },
                ).jsonObject
                val html = io.orenlab.codeclone.jetbrains.ui.render.WorkspaceInsightsHtmlRenderer
                    .renderAuditTrailHtml(payload, project.name)
                ApplicationManager.getApplication().invokeLater { onHtml(html) }
            }.onFailure { error ->
                notify(error.message ?: "Audit trail failed", NotificationType.ERROR)
            }
        }
    }

    fun loadFindingPreview(item: FindingItem, onResult: (String, String) -> Unit) {
        scope.launch {
            runCatching {
                ensureConnected()
                val finding = client.callTool(
                    "get_finding",
                    buildJsonObject {
                        put("root", absoluteRoot())
                        put("finding_id", item.id)
                    },
                ).jsonObject
                val markdown = finding["markdown"]?.jsonPrimitive?.content
                    ?: formatFindingFallback(item, finding)
                ApplicationManager.getApplication().invokeLater {
                    onResult(item.title, markdown)
                }
            }.onFailure {
                ApplicationManager.getApplication().invokeLater {
                    onResult(item.title, formatFindingFallback(item, null))
                }
            }
        }
    }

    fun loadMemoryPreview(record: io.orenlab.codeclone.jetbrains.memory.MemoryRecordItem, onResult: (String, String) -> Unit) {
        scope.launch {
            runCatching {
                ensureConnected()
                val response = client.callTool(
                    "query_engineering_memory",
                    buildJsonObject {
                        put("root", absoluteRoot())
                        put("mode", "get")
                        put("record_id", record.id)
                    },
                ).jsonObject
                val payload = response["payload"]?.jsonObject
                val detail = payload?.get("record")?.jsonObject ?: payload
                val body = buildString {
                    appendLine("Type: ${detail?.get("type")?.jsonPrimitive?.content ?: record.type}")
                    appendLine("Status: ${detail?.get("status")?.jsonPrimitive?.content ?: record.status}")
                    appendLine("Confidence: ${detail?.get("confidence")?.jsonPrimitive?.content ?: record.confidence ?: "—"}")
                    appendLine()
                    append(detail?.get("statement")?.jsonPrimitive?.content ?: record.statement)
                }
                ApplicationManager.getApplication().invokeLater {
                    onResult(record.id, body.trim())
                }
            }.onFailure {
                ApplicationManager.getApplication().invokeLater {
                    onResult(record.id, record.statement)
                }
            }
        }
    }

    private fun formatFindingFallback(item: FindingItem, payload: JsonObject?): String = buildString {
        appendLine("ID: ${item.id}")
        appendLine("Kind: ${item.kind}")
        appendLine("Scope: ${item.scope}")
        appendLine("Priority: ${item.priority}")
        item.path?.let { appendLine("Location: $it${item.line?.let { line -> ":$line" } ?: ""}") }
        appendLine()
        payload?.get("summary")?.jsonPrimitive?.content?.let {
            appendLine(it)
            appendLine()
        }
        append("Double-click or use the context menu to reveal source or open remediation.")
    }

    fun openAuditTrail() {
        scope.launch {
            runCatching {
                ensureConnected()
                if (!client.hasTool("get_controller_audit_trail")) {
                    throw McpClientException("Audit trail requires CodeClone MCP with IDE governance channel.")
                }
                val payload = client.callTool(
                    "get_controller_audit_trail",
                    buildJsonObject {
                        put("root", absoluteRoot())
                        put("limit", 50)
                    },
                ).jsonObject
                val markdown = WorkspaceInsightsFormatter.formatAuditTrailMarkdown(
                    payload,
                    project.name,
                )
                openScratch("CodeClone Audit Trail", markdown)
            }.onFailure { error ->
                notify(error.message ?: "Audit trail failed", NotificationType.ERROR)
            }
        }
    }

    fun syncMemoryFromRunAsync(onDone: (Throwable?) -> Unit = {}) {
        scope.launch {
            runCatching {
                ensureConnected()
                if (!client.hasTool("manage_engineering_memory")) {
                    throw McpClientException("Engineering Memory is not available on this MCP server.")
                }
                val result = client.callTool(
                    "manage_engineering_memory",
                    buildJsonObject {
                        put("root", absoluteRoot())
                        put("action", "refresh_from_run")
                    },
                ).jsonObject
                if (result["status"]?.jsonPrimitive?.content != "ok") {
                    val message = result["message"]?.jsonPrimitive?.content ?: "Memory sync failed."
                    throw McpClientException(message)
                }
            }.onFailure { error ->
                notify(error.message ?: "Memory sync failed", NotificationType.ERROR)
                onDone(error)
            }.onSuccess {
                notify("Engineering memory synced from the latest analysis run.", NotificationType.INFORMATION)
                refreshWorkspaceContextAsync(onDone)
            }
        }
    }

    fun approveMemoryRecord(recordId: String) = memoryDecision(recordId, approve = true)

    fun rejectMemoryRecord(recordId: String) = memoryDecision(recordId, approve = false)

    private fun memoryDecision(recordId: String, approve: Boolean) {
        scope.launch {
            runCatching {
                ensureConnected()
                val actor = governanceActor()
                if (approve) {
                    MemoryGovernance.approveRecord(client, absoluteRoot(), recordId, actor)
                } else {
                    MemoryGovernance.rejectRecord(client, absoluteRoot(), recordId, actor)
                }
            }.onFailure { error ->
                notify(error.message ?: "Memory governance failed", NotificationType.ERROR)
            }.onSuccess {
                notify(
                    if (approve) "Memory record approved." else "Memory record rejected.",
                    NotificationType.INFORMATION,
                )
                refreshMemoryAsync()
            }
        }
    }

    private fun analyzeAsync(scopeKind: AnalysisScope, onDone: (Throwable?) -> Unit) {
        scope.launch {
            runCatching {
                setBusy(true)
                ensureConnected()
                val root = absoluteRoot()
                val settings = CodeCloneSettings.getInstance()
                val analysis = AnalysisSettingsResolver.resolve(settings.config)
                val coverageXml = CoverageXmlResolver.resolve(
                    root,
                    settings.config.coverageXml,
                    settings.config.autoDetectCoverageXml,
                )
                val payload = when (scopeKind) {
                    AnalysisScope.FULL -> client.callTool(
                        "analyze_repository",
                        buildJsonObject {
                            put("root", root)
                            put("cache_policy", settings.config.cachePolicy)
                            for ((key, value) in analysis.overrides) {
                                put(key, value)
                            }
                            coverageXml?.let { put("coverage_xml", it) }
                        },
                    ).jsonObject

                    AnalysisScope.CHANGED -> client.callTool(
                        "analyze_changed_paths",
                        buildJsonObject {
                            put("root", root)
                            put("git_diff_ref", settings.config.changedDiffRef)
                            put("cache_policy", settings.config.cachePolicy)
                            for ((key, value) in analysis.overrides) {
                                put(key, value)
                            }
                            coverageXml?.let { put("coverage_xml", it) }
                        },
                    ).jsonObject
                }
                val profileSuffix = if (analysis.profileId == AnalysisSettingsResolver.PROFILE_DEFAULTS) {
                    ""
                } else {
                    " (${analysis.label})"
                }
                val next = RunArtifactsLoader.loadAfterRun(client, root, payload).copy(
                    lastScope = if (scopeKind == AnalysisScope.CHANGED) "changed" else "full",
                )
                _state.value = next
                notify(
                    "Analysis complete$profileSuffix — health ${next.healthScore ?: "n/a"} (${next.healthGrade ?: "?"})",
                    NotificationType.INFORMATION,
                )
            }.onFailure { error ->
                LOG.warn("CodeClone analysis failed", error)
                notify(error.message ?: "Analysis failed", NotificationType.ERROR)
                onDone(error)
            }.onSuccess {
                onDone(null)
            }
            setBusy(false)
            fireChanged()
        }
    }

    private fun governanceActor(): String =
        System.getProperty("user.name")?.trim()?.takeIf { it.isNotEmpty() } ?: "jetbrains-user"

    private fun setBusy(value: Boolean) {
        busy = value
        updateConnectionSummary()
    }

    private fun updateConnectionSummary() {
        val summary = when {
            busy -> "analyzing"
            client.isConnected() -> if (_state.value.runId != null) "ready" else "connected"
            else -> "disconnected"
        }
        _state.value = _state.value.copy(connectionSummary = summary)
    }

    private fun openScratch(title: String, content: String) {
        ApplicationManager.getApplication().invokeLater {
            val language = com.intellij.lang.Language.findLanguageByID("Markdown")
                ?: com.intellij.openapi.fileTypes.PlainTextLanguage.INSTANCE
            val file = com.intellij.ide.scratch.ScratchRootType.getInstance().createScratchFile(
                project,
                title,
                language,
                content,
            ) ?: return@invokeLater
            com.intellij.openapi.fileEditor.FileEditorManager.getInstance(project).openFile(file, true)
        }
    }

    private fun notify(message: String, type: NotificationType) {
        ApplicationManager.getApplication().invokeLater {
            Notification("CodeClone", "CodeClone", message, type).notify(project)
        }
    }

    private fun fireChanged() {
        ApplicationManager.getApplication().invokeLater {
            listeners.forEach { it.invoke() }
        }
    }

    override fun dispose() {
        client.dispose()
    }

    companion object {
        fun getInstance(project: Project): CodeCloneProjectService =
            project.getService(CodeCloneProjectService::class.java)
    }
}
