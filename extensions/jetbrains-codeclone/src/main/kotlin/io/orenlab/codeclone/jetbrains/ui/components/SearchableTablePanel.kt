package io.orenlab.codeclone.jetbrains.ui.components

import com.intellij.ui.SearchTextField
import com.intellij.ui.table.TableView
import com.intellij.util.ui.JBUI
import com.intellij.util.ui.ListTableModel
import java.awt.BorderLayout
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.event.DocumentEvent
import com.intellij.ui.DocumentAdapter

class SearchableTablePanel<T : Any>(
    private val table: TableView<T>,
    private val filter: (T, String) -> Boolean,
    placeholder: String,
) : JPanel(BorderLayout()) {
    private val searchField = SearchTextField(false).apply {
        textEditor.emptyText.text = placeholder
    }
    private var allRows: List<T> = emptyList()

    init {
        border = JBUI.Borders.empty()
        add(searchField, BorderLayout.NORTH)
        add(table, BorderLayout.CENTER)
        searchField.addDocumentListener(object : DocumentAdapter() {
            override fun textChanged(event: DocumentEvent) {
                applyFilter(searchField.text.trim())
            }
        })
    }

    fun component(): JComponent = this

    fun setRows(rows: List<T>) {
        allRows = rows
        applyFilter(searchField.text.trim())
    }

    fun selectedRow(): T? = table.selectedObject

    fun clearSelection() {
        table.clearSelection()
    }

    private fun applyFilter(query: String) {
        val filtered = if (query.isBlank()) {
            allRows
        } else {
            val needle = query.lowercase()
            allRows.filter { filter(it, needle) }
        }
        @Suppress("UNCHECKED_CAST")
        (table.model as ListTableModel<T>).items = filtered
        if (filtered.isNotEmpty() && table.selectedRow < 0) {
            table.selectionModel.setSelectionInterval(0, 0)
        }
    }
}
