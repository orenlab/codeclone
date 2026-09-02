package io.orenlab.codeclone.jetbrains.settings

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.util.xmlb.XmlSerializerUtil

@Service(Service.Level.APP)
@State(name = "CodeCloneSettings", storages = [Storage("codeclone.xml")])
class CodeCloneSettings : PersistentStateComponent<CodeCloneSettings.State> {
    data class State(
        var mcpCommand: String = "auto",
        var mcpArgs: String = "",
        var analysisProfile: String = "defaults",
        var changedDiffRef: String = "HEAD",
        var showStatusBar: Boolean = true,
        var coverageXml: String = "",
        var autoDetectCoverageXml: Boolean = true,
        var minLoc: Int = 10,
        var minStmt: Int = 6,
        var blockMinLoc: Int = 20,
        var blockMinStmt: Int = 8,
        var segmentMinLoc: Int = 20,
        var segmentMinStmt: Int = 10,
    )

    private var myState = State()

    /** Live settings bean for UI binding and runtime reads. */
    val config: State
        get() = myState

    override fun getState(): State = myState

    override fun loadState(state: State) {
        XmlSerializerUtil.copyBean(state, myState)
    }

    fun mcpArgsList(): List<String> =
        myState.mcpArgs.split(Regex("\\s+")).map { it.trim() }.filter { it.isNotEmpty() }

    companion object {
        fun getInstance(): CodeCloneSettings =
            ApplicationManager.getApplication().getService(CodeCloneSettings::class.java)
    }
}
