package io.orenlab.codeclone.jetbrains.settings

import java.util.Properties
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * Ratchet for the cache controls CodeClone 2.1.0a2 withdrew from the MCP surface.
 *
 * `cache_policy`, `cache_path` and `max_cache_size_mb` are no longer per-call tool
 * arguments: managing the physical cache backend is operator configuration, and the
 * server refuses those names on every tool.
 *
 * The defect this forbids has two halves, and the second is the sharper one:
 *
 *  1. A persisted setting the server refuses is worse than no setting. A tool's argument
 *     model is built from its handler signature and unknown keys are dropped, so to a
 *     client that still sends the value, "silently ignored" is indistinguishable from
 *     "honoured" -- the call succeeds and the value goes nowhere.
 *  2. Rendering that value as an Overview detail row makes a presentation surface assert
 *     a property of the run that never reached the producer. A renderer must not state a
 *     fact the canonical path never produced.
 *
 * Re-wiring is not the remedy. The control was withdrawn deliberately as a breaking
 * change; a per-workspace cache policy would reverse it. So absence is the contract, and
 * absence is what these tests pin.
 */
class WithdrawnCacheControlTest {
    private val withdrawn = setOf(
        "cachePolicy",
        "cachePath",
        "maxCacheSizeMb",
        "cache_policy",
        "cache_path",
        "max_cache_size_mb",
    )

    @Test
    fun `settings state persists no withdrawn cache control`() {
        val fields = CodeCloneSettings.State::class.java.declaredFields.map { it.name }

        // Reach witness: prove reflection actually sees this class's fields, so a rename
        // or a reflection failure cannot make the assertion below pass vacuously.
        assertTrue(
            fields.contains("analysisProfile"),
            "reflection did not reach CodeCloneSettings.State; saw fields=$fields",
        )

        val offered = fields.filter { it in withdrawn }
        assertEquals(
            emptyList<String>(),
            offered,
            "CodeCloneSettings.State persists withdrawn cache control(s) the MCP server refuses: $offered",
        )
    }

    @Test
    fun `message bundle declares no label for a withdrawn cache control`() {
        val stream = javaClass.getResourceAsStream("/messages/CodeCloneBundle.properties")
        assertNotNull(stream, "CodeCloneBundle.properties is not on the test classpath")

        val bundle = Properties().apply { stream!!.use { load(it) } }

        // Reach witness: a sibling key from the same Analysis section must be present,
        // so an empty or unloadable bundle cannot be read as "the key is gone".
        assertTrue(
            bundle.containsKey("overview.field.analysis_profile"),
            "bundle loaded but has no overview.field.* keys; the probe is not reaching the file",
        )

        val offered = bundle.stringPropertyNames().filter { key ->
            key == "overview.field.cache_policy" || withdrawn.any { key.endsWith(".$it") }
        }.sorted()
        assertEquals(
            emptyList<String>(),
            offered,
            "message bundle labels withdrawn cache control(s) the MCP server refuses: $offered",
        )
    }
}
