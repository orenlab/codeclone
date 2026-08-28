package io.orenlab.codeclone.jetbrains.analysis

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path

class CoverageXmlResolverTest {
    @TempDir
    lateinit var root: Path

    @Test
    fun `auto detect finds workspace coverage xml`() {
        Files.writeString(root.resolve("coverage.xml"), "<coverage/>")
        assertEquals("coverage.xml", CoverageXmlResolver.resolve(root.toString(), "", autoDetect = true))
    }

    @Test
    fun `configured relative path must stay inside workspace`() {
        Files.writeString(root.resolve("reports").also { Files.createDirectories(it) }.resolve("coverage.xml"), "<coverage/>")
        assertEquals(
            "reports/coverage.xml",
            CoverageXmlResolver.resolve(root.toString(), "reports/coverage.xml", autoDetect = false),
        )
    }

    @Test
    fun `paths outside workspace are rejected`() {
        assertNull(CoverageXmlResolver.resolve(root.toString(), "../coverage.xml", autoDetect = false))
    }

    @Test
    fun `auto detect is skipped when disabled`() {
        Files.writeString(root.resolve("coverage.xml"), "<coverage/>")
        assertNull(CoverageXmlResolver.resolve(root.toString(), "", autoDetect = false))
    }
}
