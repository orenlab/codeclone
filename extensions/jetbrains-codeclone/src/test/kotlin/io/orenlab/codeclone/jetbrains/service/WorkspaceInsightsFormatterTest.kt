package io.orenlab.codeclone.jetbrains.service

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class WorkspaceInsightsFormatterTest {
    @Test
    fun `parseSummary extracts workspace session fields`() {
        val payload = buildJsonObject {
            putJsonObject("workspace") { put("health", "clean") }
            putJsonObject("counts") {
                put("live_agents", 1)
                put("active_intents", 2)
                put("visible_intents", 3)
            }
            putJsonObject("latest_run") {
                put("run_id", "abc123")
                put("health", 91)
            }
            putJsonObject("audit") {
                put("enabled", "true")
                put("storage", "sqlite")
            }
        }
        val parsed = SessionInsightsLoader.parseSummary(payload)
        assertEquals("clean", parsed.workspaceHealth)
        assertEquals(1, parsed.liveAgents)
        assertEquals(2, parsed.activeIntents)
        assertEquals("abc123", parsed.latestRunId)
        assertEquals(91, parsed.latestRunHealth)
        assertTrue(parsed.auditEnabled)
        assertEquals("sqlite", parsed.auditStorage)
    }

    @Test
    fun `formatSessionStatsMarkdown includes workspace health`() {
        val payload = buildJsonObject {
            putJsonObject("workspace") {
                put("root", "/tmp/repo")
                put("health", "active")
            }
            putJsonObject("counts") {
                put("live_agents", 0)
                put("active_intents", 0)
                put("visible_intents", 0)
                put("stale", 0)
                put("expired", 0)
                put("recoverable", 0)
            }
            putJsonObject("latest_run") { put("cache_present", "false") }
        }
        val markdown = WorkspaceInsightsFormatter.formatSessionStatsMarkdown(payload, "demo")
        assertTrue(markdown.contains("Workspace health: active"))
        assertTrue(markdown.contains("demo"))
    }

    @Test
    fun `formatAgeSeconds renders minutes`() {
        assertEquals("2m ago", WorkspaceInsightsFormatter.formatAgeSeconds(120))
    }
}
