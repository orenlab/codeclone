package io.orenlab.codeclone.jetbrains.actions

import com.intellij.openapi.options.ShowSettingsUtil
import com.intellij.openapi.project.Project
import io.orenlab.codeclone.jetbrains.settings.CodeCloneSettingsConfigurable

class OpenCodeCloneSettingsAction : CodeCloneProjectAction() {
    override fun perform(project: Project) {
        ShowSettingsUtil.getInstance().showSettingsDialog(project, CodeCloneSettingsConfigurable::class.java)
    }
}
