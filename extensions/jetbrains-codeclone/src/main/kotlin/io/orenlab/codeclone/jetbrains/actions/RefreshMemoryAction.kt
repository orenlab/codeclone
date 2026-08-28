package io.orenlab.codeclone.jetbrains.actions

import com.intellij.openapi.project.Project
import io.orenlab.codeclone.jetbrains.toolwindow.CodeCloneToolWindowPanels

class RefreshMemoryAction : CodeCloneProjectAction() {
    override fun perform(project: Project) {
        CodeCloneToolWindowPanels.getInstance(project).service.refreshMemoryAsync()
    }
}
