package io.orenlab.codeclone.jetbrains.mcp

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

/**
 * The JSON-RPC `id` of an MCP response is decoded with `kotlinx.serialization.json`'s
 * own [kotlinx.serialization.json.intOrNull], the same reader the rest of this plugin
 * uses. A private `JsonPrimitive.intOrNull` inside the client would shadow it and read
 * the same frame differently.
 */
class McpResponseIdTest {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    private fun frame(raw: String): JsonObject = json.parseToJsonElement(raw) as JsonObject

    @Test
    fun `a plain integer id is decoded`() {
        assertEquals(7, decodeResponseId(frame("""{"jsonrpc":"2.0","id":7,"result":{}}""")))
    }

    // Divergence side A: a JSON number the stock reader resolves and a
    // String.toIntOrNull shadow drops. `4e1` is the number 40.
    @Test
    fun `an exponent-form integer id resolves to its integer value`() {
        assertEquals(40, decodeResponseId(frame("""{"jsonrpc":"2.0","id":4e1,"result":{}}""")))
    }

    // Divergence side A, second shape: the stock reader skips surrounding whitespace.
    @Test
    fun `a padded numeric id resolves to its integer value`() {
        assertEquals(42, decodeResponseId(frame("""{"jsonrpc":"2.0","id":" 42 ","result":{}}""")))
    }

    // Divergence side B: `+42` is not a JSON number. Integer.parseInt accepts the
    // leading plus, the stock reader does not, and accepting it would complete the
    // pending request keyed 42 from a frame that never carried that id.
    @Test
    fun `a leading-plus id is not an integer id`() {
        assertNull(decodeResponseId(frame("""{"jsonrpc":"2.0","id":"+42","result":{}}""")))
    }

    @Test
    fun `a fractional id is not an integer id`() {
        assertNull(decodeResponseId(frame("""{"jsonrpc":"2.0","id":1.5,"result":{}}""")))
    }

    @Test
    fun `an id past Int range is not an integer id`() {
        assertNull(decodeResponseId(frame("""{"jsonrpc":"2.0","id":2147483648,"result":{}}""")))
    }

    @Test
    fun `an absent id is not an integer id`() {
        assertNull(decodeResponseId(frame("""{"jsonrpc":"2.0","result":{}}""")))
    }

    @Test
    fun `a structured id is rejected loudly, not silently coerced`() {
        assertThrows<IllegalArgumentException> {
            decodeResponseId(frame("""{"jsonrpc":"2.0","id":{"n":1},"result":{}}"""))
        }
    }
}
