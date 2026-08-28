package io.orenlab.codeclone.jetbrains.settings

import com.intellij.openapi.options.BoundConfigurable
import com.intellij.openapi.ui.DialogPanel
import com.intellij.ui.dsl.builder.bindItem
import com.intellij.ui.dsl.builder.bindSelected
import com.intellij.ui.dsl.builder.bindText
import com.intellij.ui.dsl.builder.panel
import com.intellij.util.ui.JBUI

class CodeCloneSettingsConfigurable : BoundConfigurable("CodeClone") {
    private val settings = CodeCloneSettings.getInstance()

    private var analysisProfile: String?
        get() = settings.config.analysisProfile
        set(value) {
            if (value != null) {
                settings.config.analysisProfile = value
            }
        }

    private var cachePolicy: String?
        get() = settings.config.cachePolicy
        set(value) {
            if (value != null) {
                settings.config.cachePolicy = value
            }
        }

    override fun createPanel(): DialogPanel = panel {
        row("MCP command:") {
            textField()
                .bindText(settings.config::mcpCommand)
                .comment("Use auto to probe workspace .venv, PATH, then monorepo uv fallback.")
        }
        row("MCP extra args:") {
            textField()
                .bindText(settings.config::mcpArgs)
                .comment("Space-separated args. Transport is always forced to stdio.")
        }
        row("Changed-files diff ref:") {
            textField()
                .bindText(settings.config::changedDiffRef)
        }
        row("Analysis profile:") {
            comboBox(listOf("defaults", "deeperReview", "custom"))
                .bindItem(::analysisProfile)
                .comment("defaults uses repo/pyproject thresholds; deeperReview lowers clone detection thresholds.")
        }
        row("Coverage XML path:") {
            textField()
                .bindText(settings.config::coverageXml)
                .comment("Optional repo-relative path. Leave empty to auto-detect coverage.xml in the project root.")
        }
        row {
            checkBox("Auto-detect coverage.xml in workspace root")
                .bindSelected(settings.config::autoDetectCoverageXml)
        }
        row("Cache policy:") {
            comboBox(listOf("reuse", "off"))
                .bindItem(::cachePolicy)
        }
        row {
            checkBox("Show status bar widget")
                .bindSelected(settings.config::showStatusBar)
        }
    }.apply {
        border = JBUI.Borders.empty(8)
    }
}
