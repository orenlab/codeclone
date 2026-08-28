package io.orenlab.codeclone.jetbrains.ui.render

import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class WorkspaceInsightsHtmlRendererTest {
    @Test
    fun `session stats html escapes workspace name and includes health pill`() {
        val payload = buildJsonObject {
            put(
                "workspace",
                buildJsonObject {
                    put("health", "clean")
                    put("root", "/tmp/demo<script>")
                },
            )
            put(
                "counts",
                buildJsonObject {
                    put("live_agents", 1)
                    put("active_intents", 2)
                    put("visible_intents", 2)
                    put("stale", 0)
                    put("expired", 0)
                    put("recoverable", 0)
                },
            )
            put(
                "latest_run",
                buildJsonObject {
                    put("cache_present", false)
                },
            )
        }
        val html = WorkspaceInsightsHtmlRenderer.renderSessionStatsHtml(payload, "Demo<script>")
        assertTrue(html.contains("health-clean"))
        assertFalse(html.contains("Demo<script>"))
        assertTrue(html.contains("Demo&lt;script&gt;"))
        assertTrue(html.contains("Workspace Session Stats"))
    }

    @Test
    fun `audit trail html includes events table`() {
        val payload = buildJsonObject {
            put("status", "ok")
            put(
                "counts",
                buildJsonObject {
                    put("total_events", 1)
                    put("intent_events", 1)
                    put("contract_events", 0)
                    put("receipt_events", 0)
                    put("violation_events", 0)
                },
            )
            put(
                "events",
                buildJsonArray {
                    add(
                        buildJsonObject {
                            put("summary", "finish accepted")
                            put("event_type", "finish")
                            put("created_at_utc", "2026-06-22T10:00:00Z")
                        },
                    )
                },
            )
        }
        val html = WorkspaceInsightsHtmlRenderer.renderAuditTrailHtml(payload, "demo")
        assertTrue(html.contains("Recent events"))
        assertTrue(html.contains("finish accepted"))
    }

    @Test
    fun `shared styles avoid swing unsupported css`() {
        val css = WorkspaceInsightsHtmlRenderer.sharedStyles()
        assertFalse(css.contains("@media"))
        assertFalse(css.contains("font-variant"))
        assertFalse(css.contains("border-radius"))
    }
}
