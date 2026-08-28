package io.orenlab.codeclone.jetbrains.actions

import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.project.Project
import io.orenlab.codeclone.jetbrains.service.FindingItem
import io.orenlab.codeclone.jetbrains.toolwindow.CodeCloneToolWindowPanels

class MarkFindingReviewedAction : CodeCloneProjectAction() {
    override fun isActionEnabled(event: AnActionEvent, project: Project): Boolean {
        val panels = CodeCloneToolWindowPanels.getInstance(project)
        return selectedFinding(project) != null && panels.service.state.value.runId != null
    }

    override fun perform(project: Project) {
        val item = selectedFinding(project) ?: return
        CodeCloneToolWindowPanels.getInstance(project).service.markFindingReviewed(item)
    }

    private fun selectedFinding(project: Project): FindingItem? =
        CodeCloneToolWindowPanels.getInstance(project).selectedFinding()
}
