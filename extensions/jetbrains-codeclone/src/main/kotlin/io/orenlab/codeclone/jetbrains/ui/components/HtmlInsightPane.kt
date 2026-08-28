package io.orenlab.codeclone.jetbrains.ui.components

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.Logger
import com.intellij.util.ui.JBUI
import io.orenlab.codeclone.jetbrains.ui.render.WorkspaceInsightsHtmlRenderer
import java.awt.BorderLayout
import javax.swing.JEditorPane
import javax.swing.JPanel
import javax.swing.JScrollPane

class HtmlInsightPane : JPanel(BorderLayout()) {
    private val editorPane = JEditorPane().apply {
        isEditable = false
        contentType = "text/plain"
        border = JBUI.Borders.empty()
        text = "Load a report to preview structured insights."
    }

    init {
        add(JScrollPane(editorPane), BorderLayout.CENTER)
    }

    fun showPlaceholder(message: String) {
        setHtml(wrapBody("<p class=\"muted\">${escapeHtml(message)}</p>"))
    }

    fun setHtmlDocument(html: String) {
        ApplicationManager.getApplication().invokeLater {
            setHtml(html)
        }
    }

    private fun setHtml(html: String) {
        try {
            editorPane.contentType = "text/html"
            editorPane.text = html
            editorPane.caretPosition = 0
        } catch (error: Throwable) {
            LOG.warn("CodeClone HTML insight render failed; falling back to plain text", error)
            editorPane.contentType = "text/plain"
            editorPane.text = plainTextFallback(html)
            editorPane.caretPosition = 0
        }
    }

    companion object {
        private val LOG = Logger.getInstance(HtmlInsightPane::class.java)

        fun wrapBody(body: String, title: String = "CodeClone"): String = """
            <!DOCTYPE html>
            <html>
            <head>
            <style>${WorkspaceInsightsHtmlRenderer.sharedStyles()}</style>
            </head>
            <body>
            <h1>${escapeHtml(title)}</h1>
            $body
            </body>
            </html>
        """.trimIndent()

        fun escapeHtml(text: String): String = text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\"", "&quot;")

        private fun plainTextFallback(html: String): String =
            html.replace(Regex("<[^>]+>"), " ")
                .replace(Regex("\\s+"), " ")
                .trim()
    }
}
