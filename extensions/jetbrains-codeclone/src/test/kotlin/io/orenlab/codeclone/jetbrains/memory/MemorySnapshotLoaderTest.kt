package io.orenlab.codeclone.jetbrains.memory

import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class MemorySnapshotLoaderTest {
    @Test
    fun `parseStatusPayload reads records_by_status`() {
        val payload = buildJsonObject {
            put("backend", "sqlite")
            put("record_count", 12)
            put(
                "records_by_status",
                buildJsonObject {
                    put("draft", 3)
                    put("active", 7)
                    put("stale", 2)
                },
            )
        }
        val parsed = MemorySnapshotLoader.parseStatusPayload(payload)
        assertEquals("sqlite", parsed.backend)
        assertEquals(12, parsed.recordCount)
        assertEquals(3, parsed.recordsByStatus?.draft)
        assertEquals(7, parsed.recordsByStatus?.active)
        assertEquals(2, parsed.recordsByStatus?.stale)
    }

    @Test
    fun `parseRecordsPayload maps draft records`() {
        val payload = buildJsonObject {
            put(
                "records",
                buildJsonArray {
                    add(
                        buildJsonObject {
                            put("id", "mem-abc")
                            put("type", "risk_note")
                            put("status", "draft")
                            put("statement", "Example statement")
                            put("confidence", "inferred")
                        },
                    )
                },
            )
        }
        val records = MemorySnapshotLoader.parseRecordsPayload(payload)
        assertEquals(1, records.size)
        assertEquals("mem-abc", records[0].id)
        assertEquals("risk_note", records[0].type)
        assertEquals("draft", records[0].status)
        assertEquals("Example statement", records[0].statement)
        assertEquals("inferred", records[0].confidence)
    }
}
