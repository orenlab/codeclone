package io.orenlab.codeclone.jetbrains.ui.panels

import com.intellij.DynamicBundle
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.project.Project
import com.intellij.ui.OnePixelSplitter
import com.intellij.ui.components.JBLabel
import com.intellij.ui.dsl.builder.panel
import com.intellij.util.ui.JBUI
import io.orenlab.codeclone.jetbrains.memory.MemoryRecordItem
import io.orenlab.codeclone.jetbrains.memory.MemorySnapshot
import io.orenlab.codeclone.jetbrains.service.CodeCloneProjectService
import io.orenlab.codeclone.jetbrains.service.WorkspaceRunState
import io.orenlab.codeclone.jetbrains.ui.components.DetailPane
import io.orenlab.codeclone.jetbrains.ui.components.EmptyStatePanel
import io.orenlab.codeclone.jetbrains.ui.components.MemoryRow
import io.orenlab.codeclone.jetbrains.ui.components.MemoryTable
import io.orenlab.codeclone.jetbrains.ui.components.SearchableTablePanel
import java.awt.BorderLayout
import java.awt.CardLayout
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.event.ListSelectionListener

enum class MemoryRecordFilter {
    DRAFTS,
    STALE,
    ALL,
}

class MemoryPanel(
    private val project: Project,
    private val service: CodeCloneProjectService,
    private val messages: DynamicBundle,
) {
    private val memoryTable = MemoryTable()
    private val searchable = SearchableTablePanel(
        table = memoryTable,
        filter = { row, query ->
            val record = row.record
            listOf(record.id, record.type, record.status, record.statement, record.confidence)
                .any { it?.lowercase()?.contains(query) == true }
        },
        placeholder = messages.getMessage("memory.search.placeholder"),
    )
    private val detailPane = DetailPane(project)
    private val splitter = OnePixelSplitter(false, 0.55f).apply {
        firstComponent = searchable.component()
        secondComponent = detailPane
        dividerWidth = JBUI.scale(1)
    }
    private val statusLabel = JBLabel(" ").apply {
        border = JBUI.Borders.empty(4, 12, 6, 12)
    }
    private val toolbarPanel = JPanel(BorderLayout())
    private val dataPanel = JPanel(BorderLayout()).apply {
        add(toolbarPanel, BorderLayout.NORTH)
        add(splitter, BorderLayout.CENTER)
        add(statusLabel, BorderLayout.SOUTH)
    }
    private val emptyState = EmptyStatePanel(
        title = messages.getMessage("empty.memory.title"),
        description = messages.getMessage("empty.memory.body"),
    )
    private val cardPanel = JPanel(CardLayout()).apply {
        add(emptyState, "empty")
        add(dataPanel, "data")
    }

    private var selectedRecord: MemoryRecordItem? = null
    private var recordFilter = MemoryRecordFilter.DRAFTS
    private var lastState: WorkspaceRunState? = null

    init {
        memoryTable.selectionModel.addListSelectionListener(ListSelectionListener { event ->
            if (event.valueIsAdjusting) return@ListSelectionListener
            val record = memoryTable.selectedRecord()
            selectedRecord = record
            if (record == null) {
                detailPane.showPlaceholder(messages.getMessage("memory.detail.placeholder"))
            } else {
                detailPane.showDetail(record.id, messages.getMessage("memory.detail.loading"))
                service.loadMemoryPreview(record) { title, body ->
                    detailPane.showDetail(title, body)
                }
            }
        })
        memoryTable.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(event: MouseEvent) {
                if (event.clickCount == 2) {
                    memoryTable.selectedRecord()?.let { service.openMemoryRecord(it.id) }
                }
            }

            override fun mousePressed(event: MouseEvent) = maybePopup(event)
            override fun mouseReleased(event: MouseEvent) = maybePopup(event)

            private fun maybePopup(event: MouseEvent) {
                if (!event.isPopupTrigger) return
                val row = memoryTable.rowAtPoint(event.point)
                if (row < 0) return
                memoryTable.setRowSelectionInterval(row, row)
                val group = ActionManager.getInstance().getAction("CodeClone.MemoryPopup")
                    as? com.intellij.openapi.actionSystem.ActionGroup ?: return
                ActionManager.getInstance()
                    .createActionPopupMenu("CodeCloneMemoryPopup", group)
                    .component
                    .show(memoryTable, event.x, event.y)
            }
        })
    }

    fun component(): JComponent = ToolWindowShell.panel(cardPanel)

    fun selectedRecord(): MemoryRecordItem? = selectedRecord

    fun render(state: WorkspaceRunState) {
        lastState = state
        val memory = state.memory
        val layout = cardPanel.layout as CardLayout
        when {
            state.connectionSummary == "disconnected" -> {
                emptyState.update(
                    messages.getMessage("empty.disconnected.title"),
                    messages.getMessage("empty.disconnected.body"),
                    messages.getMessage("action.connect") to { service.connectAsync() },
                )
                layout.show(cardPanel, "empty")
                statusLabel.text = ""
            }
            !memory.supported -> {
                emptyState.update(
                    messages.getMessage("empty.memory.unsupported.title"),
                    messages.getMessage("empty.memory.unsupported.body"),
                )
                layout.show(cardPanel, "empty")
                statusLabel.text = ""
            }
            else -> {
                rebuildToolbar(state)
                val rows = rowsForFilter(memory.drafts, memory.stale, recordFilter)
                if (rows.isEmpty()) {
                    showFilterEmptyState(memory.draftCount, memory.staleCount, layout)
                } else {
                    searchable.setRows(rows)
                    layout.show(cardPanel, "data")
                    statusLabel.text = buildStatusText(memory, recordFilter)
                }
            }
        }
    }

    private fun rebuildToolbar(state: WorkspaceRunState) {
        toolbarPanel.removeAll()
        toolbarPanel.add(buildToolbar(state), BorderLayout.CENTER)
        toolbarPanel.revalidate()
        toolbarPanel.repaint()
    }

    private fun rowsForFilter(
        drafts: List<MemoryRecordItem>,
        stale: List<MemoryRecordItem>,
        filter: MemoryRecordFilter,
    ): List<MemoryRow> = when (filter) {
        MemoryRecordFilter.DRAFTS -> drafts.map { MemoryRow(it, inbox = true) }
        MemoryRecordFilter.STALE -> stale.map { MemoryRow(it, inbox = false) }
        MemoryRecordFilter.ALL -> drafts.map { MemoryRow(it, inbox = true) } +
            stale.map { MemoryRow(it, inbox = false) }
    }

    private fun showFilterEmptyState(draftCount: Int, staleCount: Int, layout: CardLayout) {
        when (recordFilter) {
            MemoryRecordFilter.DRAFTS -> {
                if (staleCount > 0) {
                    emptyState.update(
                        messages.getMessage("empty.memory.no_drafts.title"),
                        messages.getMessage("empty.memory.no_drafts.body", staleCount),
                        messages.getMessage("memory.filter.show_stale") to {
                            recordFilter = MemoryRecordFilter.STALE
                            lastState?.let { render(it) }
                        },
                    )
                } else {
                    emptyState.update(
                        messages.getMessage("empty.memory.inbox.title"),
                        messages.getMessage("empty.memory.inbox.body"),
                        messages.getMessage("action.refresh") to { service.refreshMemoryAsync() },
                    )
                }
            }
            MemoryRecordFilter.STALE -> {
                emptyState.update(
                    messages.getMessage("empty.memory.no_stale.title"),
                    messages.getMessage("empty.memory.no_stale.body"),
                    messages.getMessage("memory.filter.show_drafts") to {
                        recordFilter = MemoryRecordFilter.DRAFTS
                        lastState?.let { render(it) }
                    },
                )
            }
            MemoryRecordFilter.ALL -> {
                emptyState.update(
                    messages.getMessage("empty.memory.inbox.title"),
                    messages.getMessage("empty.memory.inbox.body"),
                    messages.getMessage("action.refresh") to { service.refreshMemoryAsync() },
                )
            }
        }
        layout.show(cardPanel, "empty")
        statusLabel.text = ""
    }

    private fun buildStatusText(memory: MemorySnapshot, filter: MemoryRecordFilter): String =
        buildString {
            append(
                when (filter) {
                    MemoryRecordFilter.DRAFTS -> messages.getMessage("memory.filter.status.drafts")
                    MemoryRecordFilter.STALE -> messages.getMessage("memory.filter.status.stale")
                    MemoryRecordFilter.ALL -> messages.getMessage("memory.filter.status.all")
                },
            )
            append(" · Backend ${memory.backend ?: "unknown"}")
            memory.recordCount?.let { append(" · $it records") }
            append(" · ${memory.draftCount} drafts · ${memory.staleCount} stale")
            if (filter == MemoryRecordFilter.STALE) {
                append(" · ${messages.getMessage("memory.filter.read_only_hint")}")
            }
        }

    private fun buildToolbar(state: WorkspaceRunState): JComponent {
        val memory = state.memory
        val bulkEnabled = recordFilter == MemoryRecordFilter.DRAFTS && memory.draftCount > 0
        return panel {
            row {
                label(messages.getMessage("memory.filter.label"))
                button("${messages.getMessage("memory.filter.drafts")} (${memory.draftCount})") {
                    applyFilter(MemoryRecordFilter.DRAFTS)
                }
                button("${messages.getMessage("memory.filter.stale")} (${memory.staleCount})") {
                    applyFilter(MemoryRecordFilter.STALE)
                }
                button(messages.getMessage("memory.filter.all")) {
                    applyFilter(MemoryRecordFilter.ALL)
                }
            }
            row {
                button(messages.getMessage("memory.bulk.select_all")) {
                    memoryTable.toggleSelectAll(true)
                }.enabled(bulkEnabled)
                button(messages.getMessage("memory.bulk.clear")) {
                    memoryTable.toggleSelectAll(false)
                }.enabled(bulkEnabled)
                button(messages.getMessage("memory.bulk.approve")) {
                    val selected = memoryTable.selectedForBulk()
                    confirmBulk("approve", selected.size) {
                        for (record in selected) {
                            service.approveMemoryRecord(record.id)
                        }
                    }
                }.enabled(bulkEnabled)
                button(messages.getMessage("memory.bulk.reject")) {
                    val selected = memoryTable.selectedForBulk()
                    confirmBulk("reject", selected.size) {
                        for (record in selected) {
                            service.rejectMemoryRecord(record.id)
                        }
                    }
                }.enabled(bulkEnabled)
                button(messages.getMessage("action.refresh")) { service.refreshMemoryAsync() }
            }
        }.apply {
            border = JBUI.Borders.empty(8, 12, 0, 12)
        }
    }

    private fun applyFilter(filter: MemoryRecordFilter) {
        recordFilter = filter
        lastState?.let { render(it) }
    }

    private fun confirmBulk(action: String, count: Int, onConfirm: () -> Unit) {
        if (count == 0) {
            Messages.showInfoMessage(
                project,
                messages.getMessage("memory.bulk.none_selected"),
                messages.getMessage("memory.bulk.confirm.title"),
            )
            return
        }
        val title = messages.getMessage("memory.bulk.confirm.title")
        val message = when (action) {
            "approve" -> messages.getMessage("memory.bulk.confirm.approve", count)
            else -> messages.getMessage("memory.bulk.confirm.reject", count)
        }
        if (Messages.showYesNoDialog(message, title, Messages.getQuestionIcon()) == Messages.YES) {
            onConfirm()
        }
    }
}
