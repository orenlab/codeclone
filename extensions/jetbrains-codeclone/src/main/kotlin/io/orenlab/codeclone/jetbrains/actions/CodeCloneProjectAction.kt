package io.orenlab.codeclone.jetbrains.actions

import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project

abstract class CodeCloneProjectAction : AnAction(), DumbAware {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT

    override fun update(event: AnActionEvent) {
        event.presentation.isVisible = true
        if (!CodeCloneActionSupport.hasOpenProject()) {
            event.presentation.isEnabled = false
            return
        }
        val project = CodeCloneActionSupport.resolveProject(event)
        event.presentation.isEnabled = project != null && isActionEnabled(event, project)
    }

    protected open fun isActionEnabled(event: AnActionEvent, project: Project): Boolean = true

    override fun actionPerformed(event: AnActionEvent) {
        val project = CodeCloneActionSupport.resolveProject(event)
            ?: CodeCloneActionSupport.resolveProjectFromManager()
            ?: return
        perform(project)
    }

    protected abstract fun perform(project: Project)
}
