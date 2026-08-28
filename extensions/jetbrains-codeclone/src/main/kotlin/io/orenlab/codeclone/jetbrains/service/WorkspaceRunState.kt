package io.orenlab.codeclone.jetbrains.service

import io.orenlab.codeclone.jetbrains.memory.MemorySnapshot
import kotlinx.serialization.json.JsonObject

data class FindingItem(
    val id: String,
    val kind: String,
    val title: String,
    val path: String?,
    val line: Int?,
    val endLine: Int?,
    val scope: String,
    val priority: Double,
    val group: String,
)

data class WorkspaceRunState(
    val runId: String? = null,
    val healthScore: Int? = null,
    val healthGrade: String? = null,
    val summary: JsonObject? = null,
    val runSummary: JsonObject? = null,
    val triage: JsonObject? = null,
    val hotspots: List<FindingItem> = emptyList(),
    val changedFindings: List<FindingItem> = emptyList(),
    val reviewedFindingIds: Set<String> = emptySet(),
    val memory: MemorySnapshot = MemorySnapshot(),
    val sessionInsights: SessionInsightsSnapshot = SessionInsightsSnapshot(),
    val lastScope: String = "full",
    val connectionSummary: String = "disconnected",
)

enum class AnalysisScope {
    FULL,
    CHANGED,
}
