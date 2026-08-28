package io.orenlab.codeclone.jetbrains.toolwindow

import com.intellij.DynamicBundle
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.actionSystem.DataSink
import com.intellij.openapi.actionSystem.UiDataProvider
import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.util.ui.JBUI
import io.orenlab.codeclone.jetbrains.memory.MemoryRecordItem
import io.orenlab.codeclone.jetbrains.service.CodeCloneProjectService
import io.orenlab.codeclone.jetbrains.service.FindingItem
import io.orenlab.codeclone.jetbrains.ui.panels.HotspotsPanel
import io.orenlab.codeclone.jetbrains.ui.panels.MemoryPanel
import io.orenlab.codeclone.jetbrains.ui.panels.OverviewAction
import io.orenlab.codeclone.jetbrains.ui.panels.OverviewPanel
import io.orenlab.codeclone.jetbrains.ui.panels.SessionInsightView
import io.orenlab.codeclone.jetbrains.ui.panels.SessionPanel
import javax.swing.JComponent
import javax.swing.JPanel
import java.awt.BorderLayout

@Service(Service.Level.PROJECT)
class CodeCloneToolWindowPanels(private val project: Project) {
    private val messages = DynamicBundle(CodeCloneToolWindowPanels::class.java, "messages.CodeCloneBundle")
    val service: CodeCloneProjectService = CodeCloneProjectService.getInstance(project)

    private var toolWindow: ToolWindow? = null
    private var tabEnsurer: (() -> Unit)? = null

    private var sessionPanel: SessionPanel? = null
    private var overviewPanel: OverviewPanel? = null
    private var hotspotsPanel: HotspotsPanel? = null
    private var memoryPanel: MemoryPanel? = null

    private var listenerRegistered = false

    fun attachToolWindow(toolWindow: ToolWindow) {
        this.toolWindow = toolWindow
    }

    fun setTabEnsurer(ensurer: () -> Unit) {
        tabEnsurer = ensurer
    }

    fun selectTab(tab: CodeCloneToolWindowTab, afterSelect: (() -> Unit)? = null) {
        val window = toolWindow ?: ToolWindowManager.getInstance(project).getToolWindow("CodeClone") ?: return
        if (!window.isVisible) {
            window.show(null)
        }
        ToolWindowManager.getInstance(project).invokeLater {
            tabEnsurer?.invoke()
            val manager = window.contentManager
            val target = manager.contents.firstOrNull {
                it.getUserData(CodeCloneToolWindowTab.CONTENT_TAB_KEY) == tab
            }
            if (target != null) {
                manager.setSelectedContent(target)
            } else {
                LOG.warn("CodeClone tab ${tab.name} is not available in tool window")
            }
            window.activate(null)
            refreshPanelsExceptOverview()
            afterSelect?.invoke()
        }
    }

    private fun refreshPanelsExceptOverview() {
        ensureListener()
        val state = service.state.value
        hotspotsPanel?.render(state)
        sessionPanel?.render(state)
        memoryPanel?.render(state)
        if (toolWindow?.contentManager?.selectedContent?.getUserData(CodeCloneToolWindowTab.CONTENT_TAB_KEY) ==
            CodeCloneToolWindowTab.OVERVIEW
        ) {
            overviewPanel?.render(state)
        }
    }

    fun showProductionTriage() {
        selectTab(CodeCloneToolWindowTab.HOTSPOTS) {
            hotspotsPanel().showTriage(service.state.value)
        }
    }

    fun showSessionStats() {
        selectTab(CodeCloneToolWindowTab.SESSION) {
            sessionPanel().showInsightView(SessionInsightView.SESSION_STATS)
        }
    }

    fun showAuditTrail() {
        selectTab(CodeCloneToolWindowTab.SESSION) {
            sessionPanel().showInsightView(SessionInsightView.AUDIT_TRAIL)
        }
    }

    fun showMemoryInbox() {
        selectTab(CodeCloneToolWindowTab.MEMORY) {
            if (service.state.value.connectionSummary != "disconnected") {
                service.refreshMemoryAsync()
            }
        }
    }

    private fun sessionPanel(): SessionPanel =
        sessionPanel ?: SessionPanel(service, messages).also { sessionPanel = it }

    private fun overviewPanel(): OverviewPanel =
        overviewPanel ?: OverviewPanel(
            service = service,
            messages = messages,
            onTab = { selectTab(it) },
            onAction = { handleOverviewAction(it) },
        ).also { overviewPanel = it }

    private fun hotspotsPanel(): HotspotsPanel =
        hotspotsPanel ?: HotspotsPanel(project, service, messages).also { hotspotsPanel = it }

    private fun memoryPanel(): MemoryPanel =
        memoryPanel ?: MemoryPanel(project, service, messages).also { memoryPanel = it }

    private fun ensureListener() {
        if (listenerRegistered) return
        listenerRegistered = true
        service.addListener { refreshAll() }
    }

    fun overview(): JComponent {
        ensureListener()
        return projectAware(overviewPanel().component())
    }

    fun hotspots(): JComponent {
        ensureListener()
        return projectAware(hotspotsPanel().component())
    }

    fun session(): JComponent {
        ensureListener()
        return projectAware(sessionPanel().component())
    }

    fun memory(): JComponent {
        ensureListener()
        return projectAware(memoryPanel().component())
    }

    private fun projectAware(content: JComponent): JComponent {
        return object : JPanel(BorderLayout()), UiDataProvider {
            init {
                border = JBUI.Borders.empty()
                add(content, BorderLayout.CENTER)
            }

            override fun uiDataSnapshot(sink: DataSink) {
                sink[CommonDataKeys.PROJECT] = project
            }
        }
    }

    fun selectedFinding(): FindingItem? = hotspotsPanel?.selectedFinding()
    fun selectedMemoryRecord(): MemoryRecordItem? = memoryPanel?.selectedRecord()

    fun refreshAll() {
        ensureListener()
        val state = service.state.value
        overviewPanel?.render(state)
        hotspotsPanel?.render(state)
        sessionPanel?.render(state)
        memoryPanel?.render(state)
    }

    private fun handleOverviewAction(action: OverviewAction) {
        when (action) {
            OverviewAction.OPEN_HOTSPOTS -> selectTab(CodeCloneToolWindowTab.HOTSPOTS)
            OverviewAction.OPEN_MEMORY -> showMemoryInbox()
            OverviewAction.OPEN_SESSION_STATS -> showSessionStats()
            OverviewAction.OPEN_AUDIT_TRAIL -> showAuditTrail()
            OverviewAction.OPEN_TRIAGE -> showProductionTriage()
            OverviewAction.OPEN_SETTINGS -> {
                com.intellij.openapi.options.ShowSettingsUtil.getInstance()
                    .showSettingsDialog(project, io.orenlab.codeclone.jetbrains.settings.CodeCloneSettingsConfigurable::class.java)
            }
        }
    }

    companion object {
        private val LOG = Logger.getInstance(CodeCloneToolWindowPanels::class.java)

        fun getInstance(project: Project): CodeCloneToolWindowPanels =
            project.getService(CodeCloneToolWindowPanels::class.java)
    }
}
