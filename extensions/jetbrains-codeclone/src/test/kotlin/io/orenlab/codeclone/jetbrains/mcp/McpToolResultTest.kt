package io.orenlab.codeclone.jetbrains.mcp

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * MCP sends `isError` on a tools/call result as a real JSON boolean.
 * The client contract is that such a result becomes a typed McpClientException,
 * never a silently rendered error string in the UI.
 */
class McpToolResultTest {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    private fun result(raw: String): JsonObject = json.parseToJsonElement(raw) as JsonObject

    @Test
    fun `a real JSON boolean isError is a tool error`() {
        val raw = """{"isError":true,"content":[{"type":"text",""" +
            """"text":"Error executing tool check_clones: baseline is not trusted"}]}"""
        assertTrue(isToolErrorResult(result(raw)))
    }

    @Test
    fun `a real JSON boolean false isError is not a tool error`() {
        assertFalse(isToolErrorResult(result("""{"isError":false,"content":[]}""")))
    }

    @Test
    fun `a result without isError is not a tool error`() {
        assertFalse(isToolErrorResult(result("""{"structuredContent":{"run_id":"dcae8a88"}}""")))
    }

    @Test
    fun `the quoted string form of isError is still honoured`() {
        assertTrue(isToolErrorResult(result("""{"isError":"true","content":[]}""")))
    }

    @Test
    fun `a non-primitive isError is not a tool error and does not throw`() {
        assertFalse(isToolErrorResult(result("""{"isError":{"nested":true}}""")))
    }
}
