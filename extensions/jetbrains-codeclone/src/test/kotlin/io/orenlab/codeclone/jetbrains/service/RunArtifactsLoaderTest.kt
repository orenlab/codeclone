package io.orenlab.codeclone.jetbrains.service

import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class RunArtifactsLoaderTest {
    @Test
    fun `parseReviewedFindingIds reads finding_id from items`() {
        val payload = buildJsonObject {
            put(
                "items",
                buildJsonArray {
                    add(
                        buildJsonObject {
                            put("finding_id", "clone:block:abc")
                            put("note", "reviewed")
                        },
                    )
                    add(
                        buildJsonObject {
                            put("id", "legacy-id")
                        },
                    )
                },
            )
        }
        val ids = RunArtifactsLoader.parseReviewedFindingIds(payload)
        assertEquals(setOf("clone:block:abc", "legacy-id"), ids)
    }

    @Test
    fun `parseReviewedFindingIds handles null payload`() {
        assertTrue(RunArtifactsLoader.parseReviewedFindingIds(null).isEmpty())
    }
}
