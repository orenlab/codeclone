package io.orenlab.codeclone.jetbrains.service

import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ProductionTriageFormatterTest {
    @Test
    fun `formatProductionTriageMarkdown renders hotspots not raw json`() {
        val state = WorkspaceRunState(
            runId = "932399c4",
            healthScore = 91,
            healthGrade = "A",
            summary = buildJsonObject {
                putJsonObject("health") {
                    put("score", 91)
                    put("grade", "A")
                }
                putJsonObject("findings") {
                    put("total", 8)
                    put("production", 6)
                }
            },
            triage = buildJsonObject {
                put("run_id", "932399c4")
                put("focus", "production")
                put("health_scope", "repository")
                putJsonObject("findings") {
                    put("total", 8)
                    put("outside_focus", 2)
                    putJsonObject("by_source_kind") {
                        put("production", 6)
                        put("test", 2)
                    }
                }
                putJsonObject("top_hotspots") {
                    put(
                        "items",
                        buildJsonArray {
                            add(
                                buildJsonObject {
                                    put("id", "clone:block:abc")
                                    put("kind", "block_clone")
                                    put("severity", "medium")
                                    put("scope", "production")
                                    put("priority", 0.82)
                                },
                            )
                        },
                    )
                }
                putJsonObject("top_suggestions") {
                    put(
                        "items",
                        buildJsonArray {
                            add(
                                buildJsonObject {
                                    put("id", "suggest:1")
                                    put("summary", "Extract shared helper")
                                },
                            )
                        },
                    )
                }
            },
        )

        val markdown = WorkspaceInsightsFormatter.formatProductionTriageMarkdown(state, "codeclone")
        assertTrue(markdown.contains("# CodeClone Production Triage"))
        assertTrue(markdown.contains("clone:block:abc"))
        assertTrue(markdown.contains("Extract shared helper"))
        assertTrue(!markdown.contains("\"top_hotspots\""))
    }
}
