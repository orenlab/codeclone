package io.orenlab.codeclone.jetbrains.actions

import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.ProjectManager

object CodeCloneActionSupport {
    fun hasOpenProject(): Boolean =
        ProjectManager.getInstance().openProjects.any { !it.isDisposed }

    fun resolveProject(event: AnActionEvent): Project? {
        event.getData(CommonDataKeys.PROJECT)?.takeIf { !it.isDisposed }?.let { return it }
        return resolveProjectFromManager()
    }

    fun resolveProjectFromManager(): Project? =
        ProjectManager.getInstance().openProjects.firstOrNull { !it.isDisposed }
}
