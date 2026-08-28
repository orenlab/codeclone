package io.orenlab.codeclone.jetbrains.service

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

data class SessionInsightsSnapshot(
    val supported: Boolean = false,
    val workspaceHealth: String? = null,
    val liveAgents: Int = 0,
    val activeIntents: Int = 0,
    val visibleIntents: Int = 0,
    val latestRunId: String? = null,
    val latestRunHealth: Int? = null,
    val auditEnabled: Boolean = false,
    val auditStorage: String? = null,
)

object SessionInsightsLoader {
    suspend fun loadSummary(
        client: io.orenlab.codeclone.jetbrains.mcp.McpClient,
        root: String,
    ): SessionInsightsSnapshot {
        if (!client.isConnected() || !client.hasTool("get_workspace_session_stats")) {
            return SessionInsightsSnapshot(supported = client.hasTool("get_workspace_session_stats"))
        }
        return try {
            val payload = client.callTool(
                "get_workspace_session_stats",
                buildJsonObject { put("root", root) },
            ).jsonObject
            parseSummary(payload)
        } catch (_: Exception) {
            SessionInsightsSnapshot(supported = true)
        }
    }

    internal fun parseSummary(payload: JsonObject): SessionInsightsSnapshot {
        val workspace = payload["workspace"]?.jsonObject
        val counts = payload["counts"]?.jsonObject
        val latest = payload["latest_run"]?.jsonObject
        val audit = payload["audit"]?.jsonObject
        return SessionInsightsSnapshot(
            supported = true,
            workspaceHealth = workspace?.get("health")?.jsonPrimitive?.content,
            liveAgents = counts?.get("live_agents")?.jsonPrimitive?.intOrNull ?: 0,
            activeIntents = counts?.get("active_intents")?.jsonPrimitive?.intOrNull ?: 0,
            visibleIntents = counts?.get("visible_intents")?.jsonPrimitive?.intOrNull ?: 0,
            latestRunId = latest?.get("run_id")?.jsonPrimitive?.content,
            latestRunHealth = latest?.get("health")?.jsonPrimitive?.intOrNull,
            auditEnabled = audit?.get("enabled")?.jsonPrimitive?.content == "true" ||
                    audit?.get("enabled")?.jsonPrimitive?.content == "1",
            auditStorage = audit?.get("storage")?.jsonPrimitive?.content,
        )
    }
}
