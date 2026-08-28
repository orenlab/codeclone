package io.orenlab.codeclone.jetbrains.ui.panels

import com.intellij.DynamicBundle
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.project.Project
import com.intellij.ui.OnePixelSplitter
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.JBUI
import io.orenlab.codeclone.jetbrains.service.CodeCloneProjectService
import io.orenlab.codeclone.jetbrains.service.FindingItem
import io.orenlab.codeclone.jetbrains.service.WorkspaceRunState
import io.orenlab.codeclone.jetbrains.ui.components.DetailPane
import io.orenlab.codeclone.jetbrains.ui.components.EmptyStatePanel
import io.orenlab.codeclone.jetbrains.ui.components.FindingRow
import io.orenlab.codeclone.jetbrains.ui.components.FindingsTable
import io.orenlab.codeclone.jetbrains.ui.components.HtmlInsightPane
import io.orenlab.codeclone.jetbrains.ui.components.SearchableTablePanel
import io.orenlab.codeclone.jetbrains.ui.render.WorkspaceInsightsHtmlRenderer
import com.intellij.ui.dsl.builder.panel
import java.awt.BorderLayout
import java.awt.CardLayout
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.event.ListSelectionListener

class HotspotsPanel(
    private val project: Project,
    private val service: CodeCloneProjectService,
    private val messages: DynamicBundle,
) {
    private val findingsTable = FindingsTable()
    private val searchable = SearchableTablePanel(
        table = findingsTable,
        filter = { row, query ->
            val item = row.item
            listOf(item.title, item.path, item.kind, item.scope, item.id, item.group)
                .any { it?.lowercase()?.contains(query) == true }
        },
        placeholder = "Filter findings…",
    )
    private val detailPane = DetailPane(project)
    private val splitter = OnePixelSplitter(false, 0.58f).apply {
        firstComponent = searchable.component()
        secondComponent = detailPane
        dividerWidth = JBUI.scale(1)
    }
    private val statusLabel = JBLabel(" ").apply {
        border = JBUI.Borders.empty(4, 12, 6, 12)
    }
    private val dataPanel = JPanel(BorderLayout()).apply {
        add(splitter, BorderLayout.CENTER)
        add(statusLabel, BorderLayout.SOUTH)
    }
    private val emptyState = EmptyStatePanel(
        title = "No findings yet",
        description = "Connect to MCP and run a workspace analysis to populate the review queue.",
        primaryAction = null,
        secondaryAction = null,
    )
    private val triagePane = HtmlInsightPane()
    private val triagePanel = JPanel(BorderLayout()).apply {
        add(buildTriageHeader(), BorderLayout.NORTH)
        add(triagePane, BorderLayout.CENTER)
    }
    private val cardPanel = JPanel(CardLayout()).apply {
        add(emptyState, "empty")
        add(dataPanel, "data")
        add(triagePanel, "triage")
    }

    private var selectedFinding: FindingItem? = null
    private var triageVisible = false
    private var hasFindingRows = false

    init {
        findingsTable.selectionModel.addListSelectionListener(ListSelectionListener { event ->
            if (event.valueIsAdjusting) return@ListSelectionListener
            val finding = findingsTable.selectedFinding()
            selectedFinding = finding
            if (finding == null) {
                detailPane.showPlaceholder(messages.getMessage("hotspots.detail.placeholder"))
            } else {
                detailPane.showDetail(finding.title, messages.getMessage("hotspots.detail.loading"))
                service.loadFindingPreview(finding) { title, body ->
                    detailPane.showDetail(title, body)
                }
            }
        })
        findingsTable.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(event: MouseEvent) {
                if (event.clickCount == 2) {
                    findingsTable.selectedFinding()?.let { service.revealFinding(it) }
                }
            }

            override fun mousePressed(event: MouseEvent) = maybePopup(event)
            override fun mouseReleased(event: MouseEvent) = maybePopup(event)

            private fun maybePopup(event: MouseEvent) {
                if (!event.isPopupTrigger) return
                val row = findingsTable.rowAtPoint(event.point)
                if (row < 0) return
                findingsTable.setRowSelectionInterval(row, row)
                val group = ActionManager.getInstance().getAction("CodeClone.HotspotsPopup")
                    as? com.intellij.openapi.actionSystem.ActionGroup ?: return
                ActionManager.getInstance()
                    .createActionPopupMenu("CodeCloneHotspotsPopup", group)
                    .component
                    .show(findingsTable, event.x, event.y)
            }
        })
    }

    fun component(): JComponent = ToolWindowShell.panel(cardPanel)

    fun showTriage(state: WorkspaceRunState) {
        triageVisible = true
        val layout = cardPanel.layout as CardLayout
        layout.show(cardPanel, "triage")
        triagePane.showPlaceholder(messages.getMessage("hotspots.triage.loading"))
        val html = WorkspaceInsightsHtmlRenderer.renderProductionTriageHtml(state, project.name)
        triagePane.setHtmlDocument(html)
    }

    private fun showFindingsViewFromTriage() {
        triageVisible = false
        val layout = cardPanel.layout as CardLayout
        layout.show(cardPanel, if (hasFindingRows) "data" else "empty")
    }

    private fun buildTriageHeader(): JComponent = panel {
        row {
            button(messages.getMessage("hotspots.triage.back")) { showFindingsViewFromTriage() }
            button(messages.getMessage("action.refresh")) { service.refreshRunAsync() }
        }
    }.apply {
        border = JBUI.Borders.empty(8, 12, 0, 12)
    }

    fun selectedFinding(): FindingItem? = selectedFinding

    fun render(state: WorkspaceRunState) {
        val rows = buildList {
            for (item in state.changedFindings) {
                add(FindingRow(item, state.reviewedFindingIds.contains(item.id)))
            }
            for (item in state.hotspots) {
                if (state.changedFindings.none { it.id == item.id }) {
                    add(FindingRow(item, state.reviewedFindingIds.contains(item.id)))
                }
            }
        }
        hasFindingRows = rows.isNotEmpty()
        val layout = cardPanel.layout as CardLayout
        if (triageVisible) {
            val html = WorkspaceInsightsHtmlRenderer.renderProductionTriageHtml(state, project.name)
            triagePane.setHtmlDocument(html)
            layout.show(cardPanel, "triage")
            return
        }
        if (rows.isEmpty()) {
            val (title, description, primary, secondary) = emptyCopy(state)
            emptyState.update(title, description, primary, secondary)
            layout.show(cardPanel, "empty")
            statusLabel.text = ""
        } else {
            searchable.setRows(rows)
            layout.show(cardPanel, "data")
            statusLabel.text = "${rows.size} findings · ${state.reviewedFindingIds.size} reviewed"
        }
    }

    private fun emptyCopy(state: WorkspaceRunState): EmptyCopy {
        return when {
            state.connectionSummary == "disconnected" -> EmptyCopy(
                messages.getMessage("empty.disconnected.title"),
                messages.getMessage("empty.disconnected.body"),
                messages.getMessage("action.connect") to { service.connectAsync() },
                null,
            )
            state.runId == null -> EmptyCopy(
                messages.getMessage("empty.no_run.title"),
                messages.getMessage("empty.no_run.body"),
                messages.getMessage("action.analyze.workspace") to { service.analyzeWorkspaceAsync() },
                messages.getMessage("action.connect") to { service.connectAsync() },
            )
            else -> EmptyCopy(
                messages.getMessage("empty.no_hotspots.title"),
                messages.getMessage("empty.no_hotspots.body"),
                messages.getMessage("action.analyze.workspace") to { service.analyzeWorkspaceAsync() },
                messages.getMessage("action.analyze.changed") to { service.analyzeChangedFilesAsync() },
            )
        }
    }

    private data class EmptyCopy(
        val title: String,
        val description: String,
        val primary: Pair<String, () -> Unit>?,
        val secondary: Pair<String, () -> Unit>?,
    )
}
