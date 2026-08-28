package io.orenlab.codeclone.jetbrains.actions

import com.intellij.openapi.project.Project
import io.orenlab.codeclone.jetbrains.service.CodeCloneProjectService

class AnalyzeWorkspaceAction : CodeCloneProjectAction() {
    override fun perform(project: Project) {
        CodeCloneProjectService.getInstance(project).analyzeWorkspaceAsync()
    }
}
