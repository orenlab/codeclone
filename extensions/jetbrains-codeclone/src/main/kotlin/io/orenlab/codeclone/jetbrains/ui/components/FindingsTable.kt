package io.orenlab.codeclone.jetbrains.ui.components

import com.intellij.icons.AllIcons
import com.intellij.ui.table.TableView
import com.intellij.util.ui.ColumnInfo
import com.intellij.util.ui.ListTableModel
import io.orenlab.codeclone.jetbrains.service.FindingItem
import javax.swing.Icon
import javax.swing.JLabel
import javax.swing.SwingConstants
import javax.swing.table.DefaultTableCellRenderer
import javax.swing.table.TableCellRenderer

data class FindingRow(val item: FindingItem, val reviewed: Boolean)

class FindingsTable : TableView<FindingRow>(ListTableModel(
    ReviewedColumn(),
    PriorityColumn(),
    KindColumn(),
    TitleColumn(),
    PathColumn(),
    LineColumn(),
    ScopeColumn(),
)) {
    init {
        setShowGrid(false)
        setStriped(true)
        setSelectionMode(javax.swing.ListSelectionModel.SINGLE_SELECTION)
        setColumnSelectionAllowed(false)
        rowHeight = rowHeight + 4
        tableHeader.reorderingAllowed = true
        if (columnModel.columnCount > 1) {
            val renderer = columnModel.getColumn(1).cellRenderer
            if (renderer is DefaultTableCellRenderer) {
                renderer.horizontalAlignment = SwingConstants.RIGHT
            }
        }
        emptyText.text = "No findings loaded yet."
    }

    fun setRows(rows: List<FindingRow>) {
        val model = model as ListTableModel<FindingRow>
        model.items = rows
        if (rows.isNotEmpty() && selectedRow < 0) {
            selectionModel.setSelectionInterval(0, 0)
        }
    }

    fun selectedFinding(): FindingItem? = selectedObject?.item
}

private class ReviewedColumn : ColumnInfo<FindingRow, String>("") {
    override fun valueOf(item: FindingRow): String = ""
    override fun getRenderer(item: FindingRow): TableCellRenderer =
        IconRenderer(if (item.reviewed) AllIcons.Actions.Checked else AllIcons.General.Warning)
    override fun getWidth(table: javax.swing.JTable): Int = 28
}

private class IconRenderer(private val icon: Icon) : DefaultTableCellRenderer() {
    override fun getTableCellRendererComponent(
        table: javax.swing.JTable?,
        value: Any?,
        isSelected: Boolean,
        hasFocus: Boolean,
        row: Int,
        column: Int,
    ): java.awt.Component {
        val label = super.getTableCellRendererComponent(table, "", isSelected, hasFocus, row, column) as JLabel
        label.icon = icon
        label.text = ""
        label.horizontalAlignment = SwingConstants.CENTER
        return label
    }
}

private class PriorityColumn : ColumnInfo<FindingRow, String>("Priority") {
    override fun valueOf(item: FindingRow): String =
        if (item.item.priority <= 0) "—" else String.format("%.1f", item.item.priority)
    override fun getWidth(table: javax.swing.JTable): Int = 64
}

private class KindColumn : ColumnInfo<FindingRow, String>("Kind") {
    override fun valueOf(item: FindingRow): String = item.item.kind
    override fun getWidth(table: javax.swing.JTable): Int = 88
}

private class TitleColumn : ColumnInfo<FindingRow, String>("Finding") {
    override fun valueOf(item: FindingRow): String = item.item.title
}

private class PathColumn : ColumnInfo<FindingRow, String>("Path") {
    override fun valueOf(item: FindingRow): String = item.item.path ?: "—"
}

private class LineColumn : ColumnInfo<FindingRow, String>("Line") {
    override fun valueOf(item: FindingRow): String = item.item.line?.toString() ?: "—"
    override fun getWidth(table: javax.swing.JTable): Int = 48
}

private class ScopeColumn : ColumnInfo<FindingRow, String>("Scope") {
    override fun valueOf(item: FindingRow): String = item.item.scope
    override fun getWidth(table: javax.swing.JTable): Int = 88
}
