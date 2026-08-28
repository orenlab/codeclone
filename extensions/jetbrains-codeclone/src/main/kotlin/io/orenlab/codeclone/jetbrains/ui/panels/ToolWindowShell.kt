package io.orenlab.codeclone.jetbrains.ui.panels

import com.intellij.util.ui.JBUI
import javax.swing.JComponent

object ToolWindowShell {
    fun panel(content: JComponent): JComponent = content.apply {
        border = JBUI.Borders.empty()
    }
}
