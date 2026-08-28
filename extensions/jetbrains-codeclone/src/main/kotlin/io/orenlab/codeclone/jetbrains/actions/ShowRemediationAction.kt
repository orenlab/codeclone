package io.orenlab.codeclone.jetbrains.actions

import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.project.Project
import io.orenlab.codeclone.jetbrains.service.FindingItem
import io.orenlab.codeclone.jetbrains.toolwindow.CodeCloneToolWindowPanels

class ShowRemediationAction : CodeCloneProjectAction() {
    override fun isActionEnabled(event: AnActionEvent, project: Project): Boolean =
        selectedFinding(project) != null

    override fun perform(project: Project) {
        val item = selectedFinding(project) ?: return
        CodeCloneToolWindowPanels.getInstance(project).service.showRemediation(item)
    }

    private fun selectedFinding(project: Project): FindingItem? =
        CodeCloneToolWindowPanels.getInstance(project).selectedFinding()
}
