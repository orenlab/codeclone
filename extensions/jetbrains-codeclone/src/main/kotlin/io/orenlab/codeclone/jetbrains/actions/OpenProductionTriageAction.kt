package io.orenlab.codeclone.jetbrains.actions

import com.intellij.openapi.project.Project
import io.orenlab.codeclone.jetbrains.service.CodeCloneProjectService

class OpenProductionTriageAction : CodeCloneProjectAction() {
    override fun perform(project: Project) {
        CodeCloneProjectService.getInstance(project).openProductionTriage()
    }
}
