package io.orenlab.codeclone.jetbrains.ui

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.StatusBar
import com.intellij.openapi.wm.StatusBarWidget
import com.intellij.openapi.wm.StatusBarWidgetFactory
import com.intellij.openapi.wm.impl.status.EditorBasedWidget
import com.intellij.util.Consumer
import io.orenlab.codeclone.jetbrains.service.CodeCloneProjectService
import io.orenlab.codeclone.jetbrains.settings.CodeCloneSettings
import java.awt.event.MouseEvent

class CodeCloneStatusBarWidgetFactory : StatusBarWidgetFactory {
    override fun getId(): String = "CodeCloneStatusBar"

    override fun getDisplayName(): String = "CodeClone"

    override fun isAvailable(project: Project): Boolean =
        CodeCloneSettings.getInstance().config.showStatusBar

    override fun createWidget(project: Project): StatusBarWidget = CodeCloneStatusBarWidget(project)

    override fun disposeWidget(widget: StatusBarWidget) = (widget as CodeCloneStatusBarWidget).dispose()

    override fun canBeEnabledOn(statusBar: StatusBar): Boolean = true
}

private class CodeCloneStatusBarWidget(project: Project) :
    EditorBasedWidget(project),
    StatusBarWidget,
    StatusBarWidget.TextPresentation {
    private val service = CodeCloneProjectService.getInstance(project)
    private val disposable = service.addListener {
        ApplicationManager.getApplication().invokeLater {
            if (!project.isDisposed) {
                myStatusBar?.updateWidget(ID())
            }
        }
    }

    override fun dispose() {
        disposable.dispose()
        super<EditorBasedWidget>.dispose()
    }

    override fun ID(): String = "CodeCloneStatusBar"

    override fun getPresentation(): StatusBarWidget.WidgetPresentation = this

    override fun getAlignment(): Float = 0f

    override fun getText(): String {
        val state = service.state.value
        return when (state.connectionSummary) {
            "analyzing" -> "CodeClone: analyzing…"
            "connected", "ready" -> {
                val run = state.runId ?: return "CodeClone: connected"
                val health = state.healthScore?.let { " — $it" } ?: ""
                "CodeClone: run $run$health"
            }

            else -> "CodeClone: disconnected"
        }
    }

    override fun getTooltipText(): String = "CodeClone structural review"

    override fun getClickConsumer(): Consumer<MouseEvent>? = null
}
