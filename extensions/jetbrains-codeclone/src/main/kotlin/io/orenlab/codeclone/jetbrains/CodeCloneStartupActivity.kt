package io.orenlab.codeclone.jetbrains

import com.intellij.openapi.project.Project
import com.intellij.openapi.startup.ProjectActivity
import io.orenlab.codeclone.jetbrains.service.CodeCloneProjectService

class CodeCloneStartupActivity : ProjectActivity {
    override suspend fun execute(project: Project) {
        val service = CodeCloneProjectService.getInstance(project)
        service.onProjectOpened()
        service.connectAsync()
    }
}
