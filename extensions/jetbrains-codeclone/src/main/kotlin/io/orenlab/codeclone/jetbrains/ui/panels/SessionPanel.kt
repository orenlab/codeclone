package io.orenlab.codeclone.jetbrains.ui.panels

import com.intellij.DynamicBundle
import com.intellij.ui.JBColor
import com.intellij.ui.OnePixelSplitter
import com.intellij.ui.components.JBLabel
import com.intellij.ui.dsl.builder.panel
import com.intellij.util.ui.JBUI
import io.orenlab.codeclone.jetbrains.service.CodeCloneProjectService
import io.orenlab.codeclone.jetbrains.service.WorkspaceRunState
import io.orenlab.codeclone.jetbrains.ui.components.HtmlInsightPane
import javax.swing.JComponent
import javax.swing.JPanel
import java.awt.BorderLayout

enum class SessionInsightView {
    OVERVIEW,
    SESSION_STATS,
    AUDIT_TRAIL,
}

class SessionPanel(
    private val service: CodeCloneProjectService,
    private val messages: DynamicBundle,
) {
    private var lastInsightView = SessionInsightView.OVERVIEW
    private val summaryPanel = JPanel(BorderLayout())
    private val htmlPane = HtmlInsightPane()
    private val splitter = OnePixelSplitter(false, 0.42f).apply {
        firstComponent = summaryPanel
        secondComponent = htmlPane
        dividerWidth = JBUI.scale(1)
    }
    private val statusLabel = JBLabel(" ").apply {
        border = JBUI.Borders.empty(4, 12, 6, 12)
        foreground = JBColor.namedColor("Label.disabledForeground", JBColor.GRAY)
    }
    private val headerPanel = JPanel(BorderLayout())
    private val root = JPanel(BorderLayout()).apply {
        add(headerPanel, BorderLayout.NORTH)
        add(splitter, BorderLayout.CENTER)
        add(statusLabel, BorderLayout.SOUTH)
    }

    init {
        htmlPane.showPlaceholder(messages.getMessage("session.hint.reports"))
    }

    fun component(): JComponent = ToolWindowShell.panel(root)

    fun render(state: WorkspaceRunState) {
        headerPanel.removeAll()
        headerPanel.add(buildHeader(state), BorderLayout.NORTH)
        headerPanel.revalidate()
        headerPanel.repaint()
        summaryPanel.removeAll()
        summaryPanel.add(buildSummary(state), BorderLayout.NORTH)
        summaryPanel.revalidate()
        summaryPanel.repaint()
        statusLabel.text = buildStatus(state)
        if (lastInsightView == SessionInsightView.OVERVIEW) {
            htmlPane.showPlaceholder(messages.getMessage("session.hint.reports"))
        }
    }

    fun showInsightView(view: SessionInsightView) {
        lastInsightView = view
        when (view) {
            SessionInsightView.SESSION_STATS -> {
                htmlPane.showPlaceholder(messages.getMessage("session.loading.stats"))
                service.loadSessionStatsHtml { html ->
                    htmlPane.setHtmlDocument(html)
                }
            }
            SessionInsightView.AUDIT_TRAIL -> {
                htmlPane.showPlaceholder(messages.getMessage("session.loading.audit"))
                service.loadAuditTrailHtml { html ->
                    htmlPane.setHtmlDocument(html)
                }
            }
            SessionInsightView.OVERVIEW -> {
                htmlPane.showPlaceholder(messages.getMessage("session.hint.reports"))
            }
        }
    }

    private fun buildHeader(state: WorkspaceRunState): JComponent = panel {
        group(messages.getMessage("session.quick.actions")) {
            row {
                button(messages.getMessage("action.session.stats")) {
                    showInsightView(SessionInsightView.SESSION_STATS)
                }.enabled(state.sessionInsights.supported)
                button(messages.getMessage("action.audit.trail")) {
                    showInsightView(SessionInsightView.AUDIT_TRAIL)
                }.enabled(state.sessionInsights.supported)
                button(messages.getMessage("session.open.editor")) {
                    when (lastInsightView) {
                        SessionInsightView.AUDIT_TRAIL -> service.openAuditTrail()
                        SessionInsightView.SESSION_STATS -> service.openSessionStats()
                        SessionInsightView.OVERVIEW -> service.openSessionStats()
                    }
                }.enabled(state.sessionInsights.supported)
            }
        }
    }.apply {
        border = JBUI.Borders.empty(8, 12, 0, 12)
    }

    private fun buildSummary(state: WorkspaceRunState): JComponent {
        val insights = state.sessionInsights
        return panel {
            group(messages.getMessage("session.summary.title")) {
                row(messages.getMessage("overview.field.run")) { label(state.runId?.take(12) ?: "—") }
                row(messages.getMessage("overview.field.scope")) { label(state.lastScope) }
                row(messages.getMessage("overview.field.reviewed")) { label(state.reviewedFindingIds.size.toString()) }
                if (insights.supported) {
                    row(messages.getMessage("overview.field.workspace_health")) {
                        label(insights.workspaceHealth ?: "unknown")
                    }
                    row(messages.getMessage("overview.field.agents")) {
                        label("${insights.liveAgents} · ${insights.activeIntents} intents")
                    }
                    row(messages.getMessage("overview.field.audit")) {
                        label(if (insights.auditEnabled) "on (${insights.auditStorage})" else "off")
                    }
                } else {
                    row { text(messages.getMessage("session.hint.governance")) }
                }
            }
            if (state.reviewedFindingIds.isNotEmpty()) {
                group(messages.getMessage("session.reviewed.title", state.reviewedFindingIds.size)) {
                    for (id in state.reviewedFindingIds.sorted().take(8)) {
                        row { label(id) }
                    }
                    if (state.reviewedFindingIds.size > 8) {
                        row { text(messages.getMessage("session.reviewed.more", state.reviewedFindingIds.size - 8)) }
                    }
                }
            }
        }.apply {
            border = JBUI.Borders.empty(8, 12, 8, 12)
        }
    }

    private fun buildStatus(state: WorkspaceRunState): String {
        val insights = state.sessionInsights
        return buildString {
            append(messages.getMessage("overview.field.scope"))
            append(": ")
            append(state.lastScope)
            if (insights.supported) {
                append(" · ")
                append(insights.workspaceHealth ?: "unknown")
                insights.latestRunId?.let { append(" · $it") }
            }
        }
    }
}
