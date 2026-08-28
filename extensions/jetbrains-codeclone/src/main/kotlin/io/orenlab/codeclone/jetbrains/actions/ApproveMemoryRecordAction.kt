package io.orenlab.codeclone.jetbrains.actions

import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.project.Project
import io.orenlab.codeclone.jetbrains.memory.MemoryRecordItem
import io.orenlab.codeclone.jetbrains.toolwindow.CodeCloneToolWindowPanels

class ApproveMemoryRecordAction : CodeCloneProjectAction() {
    override fun isActionEnabled(event: AnActionEvent, project: Project): Boolean =
        selectedMemoryRecord(project) != null

    override fun perform(project: Project) {
        val record = selectedMemoryRecord(project) ?: return
        CodeCloneToolWindowPanels.getInstance(project).service.approveMemoryRecord(record.id)
    }
}

class RejectMemoryRecordAction : CodeCloneProjectAction() {
    override fun isActionEnabled(event: AnActionEvent, project: Project): Boolean =
        selectedMemoryRecord(project) != null

    override fun perform(project: Project) {
        val record = selectedMemoryRecord(project) ?: return
        CodeCloneToolWindowPanels.getInstance(project).service.rejectMemoryRecord(record.id)
    }
}

private fun selectedMemoryRecord(project: Project): MemoryRecordItem? =
    CodeCloneToolWindowPanels.getInstance(project).selectedMemoryRecord()
