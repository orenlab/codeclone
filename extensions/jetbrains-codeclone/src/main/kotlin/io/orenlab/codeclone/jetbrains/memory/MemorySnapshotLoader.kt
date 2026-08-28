package io.orenlab.codeclone.jetbrains.memory

import io.orenlab.codeclone.jetbrains.mcp.McpClient
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

object MemorySnapshotLoader {
    const val DEFAULT_MAX_RESULTS = 50

    suspend fun load(client: McpClient, root: String): MemorySnapshot {
        if (!client.isConnected()) {
            return MemorySnapshot(connected = false)
        }
        if (!client.hasTool("query_engineering_memory")) {
            return MemorySnapshot(connected = true, supported = false)
        }
        val statusPayload = loadModePayload(client, root, "status")
        val draftsPayload = loadModePayload(client, root, "drafts")
        val stalePayload = loadModePayload(client, root, "stale")
        val statusBody = statusPayload?.let(::parseStatusPayload)
        val drafts = draftsPayload?.let(::parseRecordsPayload) ?: emptyList()
        val stale = stalePayload?.let(::parseRecordsPayload) ?: emptyList()
        val byStatus = statusBody?.recordsByStatus
        return MemorySnapshot(
            supported = true,
            connected = true,
            backend = statusBody?.backend,
            recordCount = statusBody?.recordCount,
            draftCount = byStatus?.draft ?: drafts.size,
            activeCount = byStatus?.active,
            staleCount = byStatus?.stale ?: stale.size,
            drafts = drafts,
            stale = stale,
        )
    }

    private suspend fun loadModePayload(client: McpClient, root: String, mode: String): JsonObject? {
        return try {
            val response = client.callTool(
                "query_engineering_memory",
                buildJsonObject {
                    put("root", root)
                    put("mode", mode)
                    if (mode == "drafts" || mode == "stale") {
                        put("max_results", DEFAULT_MAX_RESULTS)
                    }
                },
            ).jsonObject
            if (response["status"]?.jsonPrimitive?.content != "ok") {
                null
            } else {
                response["payload"]?.jsonObject
            }
        } catch (_: Exception) {
            null
        }
    }

    internal fun parseStatusPayload(payload: JsonObject): StatusPayload {
        val byStatus = payload["records_by_status"]?.jsonObject
        return StatusPayload(
            backend = payload["backend"]?.jsonPrimitive?.content,
            recordCount = payload["record_count"]?.jsonPrimitive?.intOrNull,
            recordsByStatus = byStatus?.let {
                RecordsByStatus(
                    draft = it["draft"]?.jsonPrimitive?.intOrNull,
                    active = it["active"]?.jsonPrimitive?.intOrNull,
                    stale = it["stale"]?.jsonPrimitive?.intOrNull,
                )
            },
        )
    }

    internal fun parseRecordsPayload(payload: JsonObject): List<MemoryRecordItem> {
        val records = payload["records"]?.jsonArray ?: return emptyList()
        return records.mapNotNull(::parseRecordElement)
    }

    internal fun parseRecordElement(element: JsonElement): MemoryRecordItem? {
        val record = element.jsonObject
        val id = record["id"]?.jsonPrimitive?.content ?: return null
        return MemoryRecordItem(
            id = id,
            type = record["type"]?.jsonPrimitive?.content ?: "unknown",
            status = record["status"]?.jsonPrimitive?.content ?: "draft",
            statement = record["statement"]?.jsonPrimitive?.content ?: "",
            confidence = record["confidence"]?.jsonPrimitive?.content,
        )
    }

    internal data class StatusPayload(
        val backend: String?,
        val recordCount: Int?,
        val recordsByStatus: RecordsByStatus?,
    )

    internal data class RecordsByStatus(
        val draft: Int?,
        val active: Int?,
        val stale: Int?,
    )
}
