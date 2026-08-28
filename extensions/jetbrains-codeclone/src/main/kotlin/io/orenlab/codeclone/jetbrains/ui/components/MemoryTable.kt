package io.orenlab.codeclone.jetbrains.ui.components

import com.intellij.icons.AllIcons
import com.intellij.ui.table.TableView
import com.intellij.util.ui.ColumnInfo
import com.intellij.util.ui.ListTableModel
import io.orenlab.codeclone.jetbrains.memory.MemoryRecordItem
import javax.swing.Icon
import javax.swing.JCheckBox
import javax.swing.JLabel
import javax.swing.SwingConstants
import javax.swing.SwingUtilities
import javax.swing.table.DefaultTableCellRenderer
import javax.swing.table.TableCellEditor
import javax.swing.table.TableCellRenderer
import java.awt.Component
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent

data class MemoryRow(
    val record: MemoryRecordItem,
    var selected: Boolean = false,
    val inbox: Boolean = true,
)

class MemoryTable : TableView<MemoryRow>(ListTableModel(
    SelectColumn(),
    IdColumn(),
    TypeColumn(),
    StatusColumn(),
    ConfidenceColumn(),
    StatementColumn(),
)) {
    init {
        setShowGrid(false)
        setStriped(true)
        setSelectionMode(javax.swing.ListSelectionModel.SINGLE_SELECTION)
        rowHeight = rowHeight + 6
        tableHeader.reorderingAllowed = false
        emptyText.text = "No memory records loaded yet."
        installCheckboxClickHandler()
    }

    fun setRows(rows: List<MemoryRow>) {
        (model as ListTableModel<MemoryRow>).items = rows
    }

    fun selectedRecord(): MemoryRecordItem? = selectedObject?.record

    fun selectedForBulk(): List<MemoryRecordItem> =
        (model as ListTableModel<MemoryRow>).items.filter { it.selected && it.inbox }.map { it.record }

    fun toggleSelectAll(select: Boolean) {
        val tableModel = model as ListTableModel<MemoryRow>
        for (row in tableModel.items) {
            if (row.inbox) row.selected = select
        }
        tableModel.fireTableDataChanged()
    }

    private fun installCheckboxClickHandler() {
        addMouseListener(
            object : MouseAdapter() {
                override fun mousePressed(event: MouseEvent) {
                    if (!SwingUtilities.isLeftMouseButton(event)) return
                    val viewRow = rowAtPoint(event.point)
                    val viewColumn = columnAtPoint(event.point)
                    if (viewRow < 0 || viewColumn != 0) return
                    val tableModel = model as ListTableModel<MemoryRow>
                    val modelRow = convertRowIndexToModel(viewRow)
                    val row = tableModel.items.getOrNull(modelRow) ?: return
                    if (!row.inbox) return
                    row.selected = !row.selected
                    tableModel.fireTableCellUpdated(modelRow, 0)
                    event.consume()
                }
            },
        )
    }
}

private class SelectColumn : ColumnInfo<MemoryRow, Boolean>("") {
    override fun valueOf(item: MemoryRow): Boolean = item.selected && item.inbox

    override fun setValue(item: MemoryRow, value: Boolean) {
        if (item.inbox) item.selected = value
    }

    override fun isCellEditable(item: MemoryRow): Boolean = item.inbox

    override fun getRenderer(item: MemoryRow): TableCellRenderer =
        if (item.inbox) CheckboxRenderer(enabled = true) else CheckboxRenderer(enabled = false)

    override fun getEditor(item: MemoryRow): TableCellEditor? =
        if (item.inbox) CheckboxEditor() else null

    override fun getWidth(table: javax.swing.JTable): Int = 36
}

private class CheckboxRenderer(private val enabled: Boolean) : TableCellRenderer {
    private val box = JCheckBox()
    private val empty = JLabel()

    override fun getTableCellRendererComponent(
        table: javax.swing.JTable?,
        value: Any?,
        isSelected: Boolean,
        hasFocus: Boolean,
        row: Int,
        column: Int,
    ): Component {
        if (!enabled) {
            empty.isOpaque = true
            empty.background = table?.background
            return empty
        }
        box.isSelected = value == true
        box.isEnabled = true
        box.background = table?.background
        box.isOpaque = true
        return box
    }
}

private class CheckboxEditor : javax.swing.AbstractCellEditor(), TableCellEditor {
    private val box = JCheckBox()
    override fun getTableCellEditorComponent(
        table: javax.swing.JTable?,
        value: Any?,
        isSelected: Boolean,
        row: Int,
        column: Int,
    ): Component {
        box.isSelected = value == true
        box.addActionListener { stopCellEditing() }
        return box
    }

    override fun getCellEditorValue(): Any = box.isSelected
}

private class IdColumn : ColumnInfo<MemoryRow, String>("ID") {
    override fun valueOf(item: MemoryRow): String = item.record.id
    override fun getRenderer(item: MemoryRow): TableCellRenderer =
        IconTextRenderer(AllIcons.FileTypes.Unknown, item.record.id)
    override fun getWidth(table: javax.swing.JTable): Int = 140
}

private class IconTextRenderer(private val icon: Icon, private val text: String) : DefaultTableCellRenderer() {
    override fun getTableCellRendererComponent(
        table: javax.swing.JTable?,
        value: Any?,
        isSelected: Boolean,
        hasFocus: Boolean,
        row: Int,
        column: Int,
    ): Component {
        val label = super.getTableCellRendererComponent(table, text, isSelected, hasFocus, row, column) as JLabel
        label.icon = icon
        return label
    }
}

private class TypeColumn : ColumnInfo<MemoryRow, String>("Type") {
    override fun valueOf(item: MemoryRow): String = item.record.type
    override fun getWidth(table: javax.swing.JTable): Int = 96
}

private class StatusColumn : ColumnInfo<MemoryRow, String>("Status") {
    override fun valueOf(item: MemoryRow): String = item.record.status
    override fun getWidth(table: javax.swing.JTable): Int = 72
}

private class ConfidenceColumn : ColumnInfo<MemoryRow, String>("Confidence") {
    override fun valueOf(item: MemoryRow): String = item.record.confidence ?: "—"
    override fun getWidth(table: javax.swing.JTable): Int = 88
}

private class StatementColumn : ColumnInfo<MemoryRow, String>("Statement") {
    override fun valueOf(item: MemoryRow): String =
        item.record.statement.trim().replace('\n', ' ').take(120).let {
            if (item.record.statement.length > 120) "$it…" else it
        }
}
