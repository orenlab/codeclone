package io.orenlab.codeclone.jetbrains.ui.components

import com.intellij.icons.AllIcons
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.JBUI
import java.awt.BorderLayout
import java.awt.FlowLayout
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.SwingConstants

class EmptyStatePanel(
    title: String,
    description: String,
    primaryAction: Pair<String, () -> Unit>? = null,
    secondaryAction: Pair<String, () -> Unit>? = null,
) : JPanel(BorderLayout()) {
    private val titleLabel = JBLabel(title, SwingConstants.CENTER).apply {
        icon = AllIcons.General.Information
        font = font.deriveFont(java.awt.Font.BOLD, font.size + 2f)
        border = JBUI.Borders.emptyBottom(8)
    }
    private val descriptionLabel = JBLabel("<html><center>$description</center></html>", SwingConstants.CENTER).apply {
        foreground = JBUI.CurrentTheme.Label.disabledForeground()
    }
    private val actionsPanel = JPanel(FlowLayout(FlowLayout.CENTER, JBUI.scale(8), 0))

    init {
        border = JBUI.Borders.empty(24, 32, 24, 32)
        val center = JPanel(BorderLayout()).apply {
            isOpaque = false
            add(titleLabel, BorderLayout.NORTH)
            add(descriptionLabel, BorderLayout.CENTER)
            add(actionsPanel, BorderLayout.SOUTH)
        }
        add(center, BorderLayout.CENTER)
        bindActions(primaryAction, secondaryAction)
    }

    fun update(
        title: String,
        description: String,
        primaryAction: Pair<String, () -> Unit>? = null,
        secondaryAction: Pair<String, () -> Unit>? = null,
    ) {
        titleLabel.text = title
        descriptionLabel.text = "<html><center>$description</center></html>"
        bindActions(primaryAction, secondaryAction)
        revalidate()
        repaint()
    }

    private fun bindActions(
        primaryAction: Pair<String, () -> Unit>?,
        secondaryAction: Pair<String, () -> Unit>?,
    ) {
        actionsPanel.removeAll()
        primaryAction?.let { (label, action) ->
            actionsPanel.add(JButton(label).apply { addActionListener { action() } })
        }
        secondaryAction?.let { (label, action) ->
            actionsPanel.add(JButton(label).apply { addActionListener { action() } })
        }
        actionsPanel.isVisible = primaryAction != null || secondaryAction != null
    }
}
