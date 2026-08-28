package io.orenlab.codeclone.jetbrains.toolwindow

import com.intellij.DynamicBundle
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Key
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.components.JBLabel
import com.intellij.ui.content.Content
import com.intellij.ui.content.ContentFactory
import com.intellij.ui.content.ContentManagerEvent
import com.intellij.ui.content.ContentManagerListener
import com.intellij.util.ui.JBUI
import io.orenlab.codeclone.jetbrains.CodeCloneIcons
import javax.swing.JPanel
import java.awt.BorderLayout

class CodeCloneToolWindowFactory : ToolWindowFactory, DumbAware {
    override fun init(toolWindow: ToolWindow) {
        toolWindow.setIcon(CodeCloneIcons.ToolWindowExpUi)
        val actionManager = ActionManager.getInstance()
        val actions = TOOLBAR_ACTION_IDS.mapNotNull { id ->
            actionManager.getAction(id) as? AnAction
        }
        if (actions.isNotEmpty()) {
            toolWindow.setTitleActions(actions)
        }
    }

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val contentManager = toolWindow.contentManager
        if (contentManager.contents.any { it.getUserData(CONTENT_READY_KEY) == true }) {
            CodeCloneToolWindowPanels.getInstance(project).refreshAll()
            return
        }

        val messages = DynamicBundle(CodeCloneToolWindowFactory::class.java, "messages.CodeCloneBundle")
        val factory = ContentFactory.getInstance()
        val panels = CodeCloneToolWindowPanels.getInstance(project)
        panels.attachToolWindow(toolWindow)
        panels.setTabEnsurer {
            ensureRemainingTabs(contentManager, factory, messages, panels)
        }

        try {
            contentManager.removeAllContents(true)
            val overview = createTabContent(
                factory = factory,
                component = panels.overview(),
                title = messages.getMessage("tab.overview"),
                tab = CodeCloneToolWindowTab.OVERVIEW,
                marker = true,
            )
            contentManager.addContent(overview)
            contentManager.setSelectedContent(overview)
            ensureRemainingTabs(contentManager, factory, messages, panels)
            panels.refreshAll()
            contentManager.addContentManagerListener(
                object : ContentManagerListener {
                    override fun selectionChanged(event: ContentManagerEvent) {
                        ensureRemainingTabs(contentManager, factory, messages, panels)
                        panels.refreshAll()
                    }
                },
            )
        } catch (error: Throwable) {
            LOG.error("CodeClone tool window failed to initialize", error)
            contentManager.removeAllContents(true)
            contentManager.addContent(createErrorContent(factory, error))
        }
    }

    private fun ensureRemainingTabs(
        contentManager: com.intellij.ui.content.ContentManager,
        factory: ContentFactory,
        messages: DynamicBundle,
        panels: CodeCloneToolWindowPanels,
    ) {
        addTabIfMissing(
            contentManager,
            factory,
            CodeCloneToolWindowTab.HOTSPOTS,
            messages.getMessage("tab.hotspots"),
        ) {
            panels.hotspots()
        }
        addTabIfMissing(
            contentManager,
            factory,
            CodeCloneToolWindowTab.SESSION,
            messages.getMessage("tab.session"),
        ) {
            panels.session()
        }
        addTabIfMissing(
            contentManager,
            factory,
            CodeCloneToolWindowTab.MEMORY,
            messages.getMessage("tab.memory"),
        ) {
            panels.memory()
        }
    }

    private fun addTabIfMissing(
        contentManager: com.intellij.ui.content.ContentManager,
        factory: ContentFactory,
        tab: CodeCloneToolWindowTab,
        title: String,
        componentSupplier: () -> javax.swing.JComponent,
    ) {
        if (contentManager.contents.any { it.getUserData(CodeCloneToolWindowTab.CONTENT_TAB_KEY) == tab }) {
            return
        }
        runCatching {
            contentManager.addContent(
                createTabContent(
                    factory = factory,
                    component = componentSupplier(),
                    title = title,
                    tab = tab,
                ),
            )
        }.onFailure { error ->
            LOG.error("CodeClone failed to create ${tab.name} tool window tab", error)
        }
    }

    private fun createTabContent(
        factory: ContentFactory,
        component: javax.swing.JComponent,
        title: String,
        tab: CodeCloneToolWindowTab,
        marker: Boolean = false,
    ): Content = factory.createContent(component, title, false).apply {
        isCloseable = false
        putUserData(CodeCloneToolWindowTab.CONTENT_TAB_KEY, tab)
        if (marker) {
            putUserData(CONTENT_READY_KEY, true)
        }
    }

    private fun createErrorContent(factory: ContentFactory, error: Throwable): Content {
        val panel = JPanel(BorderLayout()).apply {
            border = JBUI.Borders.empty(16)
            add(
                JBLabel(
                    "<html><b>CodeClone failed to load</b><br/><br/>" +
                        "${error.message ?: error.javaClass.simpleName}<br/><br/>" +
                        "See <i>Help → Show Log in Finder</i> for details.</html>",
                ),
                BorderLayout.NORTH,
            )
        }
        return factory.createContent(panel, "Error", false).apply {
            isCloseable = false
            putUserData(CONTENT_READY_KEY, true)
        }
    }

    companion object {
        private val LOG = Logger.getInstance(CodeCloneToolWindowFactory::class.java)
        private val CONTENT_READY_KEY = Key.create<Boolean>("codeclone.toolwindow.ready")

        private val TOOLBAR_ACTION_IDS = listOf(
            "CodeClone.OpenSettings",
            "CodeClone.Connect",
            "CodeClone.AnalyzeWorkspace",
            "CodeClone.AnalyzeChangedFiles",
            "CodeClone.OpenTriage",
            "CodeClone.RefreshRun",
            "CodeClone.RefreshMemory",
            "CodeClone.OpenSessionStats",
            "CodeClone.OpenAuditTrail",
        )
    }
}
