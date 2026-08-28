package io.orenlab.codeclone.jetbrains.service

import io.orenlab.codeclone.jetbrains.mcp.McpClient
import io.orenlab.codeclone.jetbrains.memory.MemorySnapshotLoader
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

object RunArtifactsLoader {
    suspend fun loadAfterRun(
        client: McpClient,
        root: String,
        runPayload: JsonObject,
    ): WorkspaceRunState {
        val runId = runPayload["run_id"]?.jsonPrimitive?.content
        val health = runPayload["health"]?.jsonObject
        val triageArgs = buildJsonObject {
            put("root", root)
            runId?.let { put("run_id", it) }
        }
        val triage = client.callTool("get_production_triage", triageArgs).jsonObject
        val hotspots = client.callTool(
            "list_hotspots",
            buildJsonObject {
                put("root", root)
                put("limit", 25)
            },
        )
        val changed = client.callTool(
            "list_findings",
            buildJsonObject {
                put("root", root)
                put("family", "all")
                put("source_kind", "production")
                put("changed_scope", true)
                put("limit", 25)
            },
        )
        val memory = MemorySnapshotLoader.load(client, root)
        val runSummary = runId?.let { id ->
            callToolObject(client, "get_run_summary", buildJsonObject { put("run_id", id) })
        }
        val reviewedPayload = runId?.let { id ->
            callToolObject(client, "list_reviewed_findings", buildJsonObject { put("run_id", id) })
        }
        val sessionInsights = SessionInsightsLoader.loadSummary(client, root)
        return WorkspaceRunState(
            runId = runId,
            healthScore = health?.get("score")?.jsonPrimitive?.intOrNull,
            healthGrade = health?.get("grade")?.jsonPrimitive?.content,
            summary = runPayload,
            runSummary = runSummary,
            triage = triage,
            hotspots = parseFindingItems(hotspots, "hotspots"),
            changedFindings = parseFindingItems(changed, "changed"),
            reviewedFindingIds = parseReviewedFindingIds(reviewedPayload),
            memory = memory,
            sessionInsights = sessionInsights,
            lastScope = "full",
            connectionSummary = "ready",
        )
    }

    internal fun parseReviewedFindingIds(payload: JsonObject?): Set<String> {
        val items = payload?.get("items")?.jsonArray ?: return emptySet()
        return items.mapNotNull { element ->
            val item = element.jsonObject
            item["finding_id"]?.jsonPrimitive?.content ?: item["id"]?.jsonPrimitive?.content
        }.toSet()
    }

    private suspend fun callToolObject(
        client: McpClient,
        toolName: String,
        arguments: JsonObject,
    ): JsonObject? {
        if (!client.hasTool(toolName)) return null
        return try {
            client.callTool(toolName, arguments).jsonObject
        } catch (_: Exception) {
            null
        }
    }

    private fun parseFindingItems(payload: JsonElement, group: String): List<FindingItem> {
        val items = payload.jsonObject["items"]?.jsonArray ?: return emptyList()
        return items.mapNotNull { element ->
            val item = element.jsonObject
            val id = item["id"]?.jsonPrimitive?.content ?: return@mapNotNull null
            val kind = item["kind"]?.jsonPrimitive?.content ?: "finding"
            val locations = item["locations"]?.jsonArray
            val firstLocation = locations?.firstOrNull()?.jsonPrimitive?.content
            val pathLine = firstLocation?.split(":", limit = 2)
            FindingItem(
                id = id,
                kind = kind,
                title = id.substringAfter(':', id),
                path = pathLine?.getOrNull(0),
                line = pathLine?.getOrNull(1)?.toIntOrNull(),
                endLine = null,
                scope = item["scope"]?.jsonPrimitive?.content ?: "production",
                priority = item["priority"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0,
                group = group,
            )
        }
    }
}
