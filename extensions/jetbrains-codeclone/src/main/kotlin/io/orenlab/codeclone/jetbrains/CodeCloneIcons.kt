package io.orenlab.codeclone.jetbrains

import com.intellij.openapi.util.IconLoader
import javax.swing.Icon

object CodeCloneIcons {
    val Logo: Icon = IconLoader.getIcon("/icons/codeclone.svg", CodeCloneIcons::class.java)
    val ToolWindow: Icon = IconLoader.getIcon("/icons/codeclone@20x20.svg", CodeCloneIcons::class.java)
    val ToolWindowExpUi: Icon =
        IconLoader.getIcon("/icons/expui/toolwindows/codeclone@20x20.svg", CodeCloneIcons::class.java)
}
