package io.orenlab.codeclone.jetbrains.analysis

import io.orenlab.codeclone.jetbrains.settings.CodeCloneSettings

object AnalysisSettingsResolver {
    const val PROFILE_DEFAULTS = "defaults"
    const val PROFILE_DEEPER_REVIEW = "deeperReview"
    const val PROFILE_CUSTOM = "custom"

    data class Resolved(
        val profileId: String,
        val label: String,
        val overrides: Map<String, Int>,
    )

    private val defaultThresholds = mapOf(
        "min_loc" to 10,
        "min_stmt" to 6,
        "block_min_loc" to 20,
        "block_min_stmt" to 8,
        "segment_min_loc" to 20,
        "segment_min_stmt" to 10,
    )

    private val deeperReviewThresholds = mapOf(
        "min_loc" to 5,
        "min_stmt" to 2,
        "block_min_loc" to 5,
        "block_min_stmt" to 2,
        "segment_min_loc" to 5,
        "segment_min_stmt" to 2,
    )

    fun resolve(state: CodeCloneSettings.State): Resolved {
        val profileId = normalizeProfile(state.analysisProfile)
        return when (profileId) {
            PROFILE_DEFAULTS -> Resolved(
                profileId = profileId,
                label = "Conservative",
                overrides = emptyMap(),
            )

            PROFILE_DEEPER_REVIEW -> Resolved(
                profileId = profileId,
                label = "Deeper review",
                overrides = deeperReviewThresholds,
            )

            else -> Resolved(
                profileId = PROFILE_CUSTOM,
                label = "Custom",
                overrides = mapOf(
                    "min_loc" to nonNegative(state.minLoc, defaultThresholds.getValue("min_loc")),
                    "min_stmt" to nonNegative(state.minStmt, defaultThresholds.getValue("min_stmt")),
                    "block_min_loc" to nonNegative(state.blockMinLoc, defaultThresholds.getValue("block_min_loc")),
                    "block_min_stmt" to nonNegative(state.blockMinStmt, defaultThresholds.getValue("block_min_stmt")),
                    "segment_min_loc" to nonNegative(state.segmentMinLoc, defaultThresholds.getValue("segment_min_loc")),
                    "segment_min_stmt" to nonNegative(state.segmentMinStmt, defaultThresholds.getValue("segment_min_stmt")),
                ),
            )
        }
    }

    private fun normalizeProfile(value: String): String =
        when (value.trim()) {
            PROFILE_DEEPER_REVIEW -> PROFILE_DEEPER_REVIEW
            PROFILE_CUSTOM -> PROFILE_CUSTOM
            else -> PROFILE_DEFAULTS
        }

    private fun nonNegative(value: Int, fallback: Int): Int =
        if (value >= 0) value else fallback
}
