package io.orenlab.codeclone.jetbrains.analysis

import io.orenlab.codeclone.jetbrains.settings.CodeCloneSettings
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class AnalysisSettingsResolverTest {
    @Test
    fun `defaults profile sends no threshold overrides`() {
        val resolved = AnalysisSettingsResolver.resolve(CodeCloneSettings.State(analysisProfile = "defaults"))
        assertEquals(AnalysisSettingsResolver.PROFILE_DEFAULTS, resolved.profileId)
        assertTrue(resolved.overrides.isEmpty())
    }

    @Test
    fun `deeper review profile sends lowered thresholds`() {
        val resolved = AnalysisSettingsResolver.resolve(CodeCloneSettings.State(analysisProfile = "deeperReview"))
        assertEquals(AnalysisSettingsResolver.PROFILE_DEEPER_REVIEW, resolved.profileId)
        assertEquals(5, resolved.overrides["min_loc"])
        assertEquals(2, resolved.overrides["min_stmt"])
    }

    @Test
    fun `custom profile uses configured thresholds`() {
        val resolved = AnalysisSettingsResolver.resolve(
            CodeCloneSettings.State(
                analysisProfile = "custom",
                minLoc = 7,
                minStmt = 3,
            ),
        )
        assertEquals(AnalysisSettingsResolver.PROFILE_CUSTOM, resolved.profileId)
        assertEquals(7, resolved.overrides["min_loc"])
        assertEquals(3, resolved.overrides["min_stmt"])
    }
}
