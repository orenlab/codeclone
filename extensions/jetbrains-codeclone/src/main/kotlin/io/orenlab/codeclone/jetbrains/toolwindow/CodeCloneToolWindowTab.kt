package io.orenlab.codeclone.jetbrains.toolwindow

import com.intellij.openapi.util.Key

enum class CodeCloneToolWindowTab {
    OVERVIEW,
    HOTSPOTS,
    SESSION,
    MEMORY,
    ;

    companion object {
        val CONTENT_TAB_KEY: Key<CodeCloneToolWindowTab> =
            Key.create("codeclone.toolwindow.tab")
    }
}
