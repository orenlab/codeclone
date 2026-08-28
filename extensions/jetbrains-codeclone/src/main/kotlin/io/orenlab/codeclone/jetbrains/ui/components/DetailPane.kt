package io.orenlab.codeclone.jetbrains.ui.components

import com.intellij.openapi.editor.ex.EditorEx
import com.intellij.openapi.fileTypes.PlainTextFileType
import com.intellij.openapi.project.Project
import com.intellij.ui.EditorTextField
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBScrollPane
import com.intellij.util.ui.JBUI
import java.awt.BorderLayout
import javax.swing.JPanel

class DetailPane(project: Project) : JPanel(BorderLayout()) {
    private val titleLabel = JBLabel(" ").apply {
        border = JBUI.Borders.empty(8, 12, 4, 12)
        font = font.deriveFont(font.style or java.awt.Font.BOLD)
    }
    private val editorField = EditorTextField("", project, PlainTextFileType.INSTANCE).apply {
        isViewer = true
        setOneLineMode(false)
        border = JBUI.Borders.empty()
    }

    init {
        border = JBUI.Borders.customLine(JBUI.CurrentTheme.CustomFrameDecorations.separatorForeground(), 1, 0, 0, 0)
        add(titleLabel, BorderLayout.NORTH)
        add(JBScrollPane(editorField), BorderLayout.CENTER)
        showPlaceholder("Select a row to preview details.")
    }

    fun showPlaceholder(message: String) {
        titleLabel.text = "Details"
        editorField.text = message
    }

    fun showDetail(title: String, body: String) {
        titleLabel.text = title
        editorField.text = body
        (editorField.editor as? EditorEx)?.scrollPane?.verticalScrollBar?.value = 0
    }
}
