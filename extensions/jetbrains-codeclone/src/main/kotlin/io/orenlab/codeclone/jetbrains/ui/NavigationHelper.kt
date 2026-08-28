package io.orenlab.codeclone.jetbrains.ui

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.LocalFileSystem
import io.orenlab.codeclone.jetbrains.service.FindingItem
import java.nio.file.Path
import kotlin.io.path.exists

object NavigationHelper {
    fun openFinding(project: Project, workspaceRoot: Path, item: FindingItem) {
        val relative = item.path ?: return
        val absolute = workspaceRoot.resolve(relative)
        if (!absolute.exists()) return
        val line = (item.line ?: 1) - 1
        ApplicationManager.getApplication().invokeLater {
            val virtualFile = LocalFileSystem.getInstance().refreshAndFindFileByPath(absolute.toString())
                ?: return@invokeLater
            OpenFileDescriptor(project, virtualFile, line.coerceAtLeast(0), 0).navigate(true)
        }
    }
}
