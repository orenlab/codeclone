package io.orenlab.codeclone.jetbrains.mcp

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path

class McpLauncherTest {
    @Test
    fun `with ide governance channel is idempotent`() {
        val args = listOf("--foo", "bar")
        val once = McpLauncher.withIdeGovernanceChannel(args)
        val twice = McpLauncher.withIdeGovernanceChannel(once)
        assertEquals(once, twice)
        assertTrue(once.contains("--ide-governance-channel"))
    }

    @Test
    fun `blocked transport args are rejected`(@TempDir temp: Path) {
        try {
            McpLauncher.resolve(temp, "codeclone-mcp", listOf("--transport", "http"))
            throw AssertionError("expected exception")
        } catch (error: McpClientException) {
            assertTrue(error.message!!.contains("--transport"))
        }
    }

    @Test
    fun `spawn environment sets workspace root and augments path`(@TempDir temp: Path) {
        val env = McpLauncher.spawnEnvironment(temp)
        assertEquals(temp.toString(), env["CODECLONE_WORKSPACE_ROOT"])
        val path = env["PATH"].orEmpty()
        assertTrue(path.contains(".local") || path.contains("homebrew") || path.contains("usr/local"))
    }

    @Test
    fun `looksLikeCodeCloneRepo accepts current layout`(@TempDir temp: Path) {
        Files.createDirectories(temp.resolve("codeclone/surfaces/mcp"))
        Files.writeString(temp.resolve("pyproject.toml"), "[project]\nname='demo'\n")
        Files.writeString(temp.resolve("codeclone/surfaces/mcp/server.py"), "# mcp\n")
        assertTrue(McpLauncher.looksLikeCodeCloneRepo(temp))
    }

    @Test
    fun `resolve prefers workspace venv launcher`(@TempDir temp: Path) {
        val launcher = temp.resolve(".venv/bin/codeclone-mcp")
        Files.createDirectories(launcher.parent)
        Files.writeString(launcher, "#!/bin/sh\n")
        launcher.toFile().setExecutable(true)
        val plan = McpLauncher.resolve(temp, "auto", emptyList())
        assertEquals("workspace-venv", plan.primary.source)
        assertNull(plan.fallback)
    }

    @Test
    fun `findCodecloneMonorepoRoot detects repo layout`(@TempDir temp: Path) {
        Files.createDirectories(temp.resolve("codeclone/surfaces/mcp"))
        Files.writeString(temp.resolve("pyproject.toml"), "[project]\nname='codeclone'\n")
        Files.writeString(temp.resolve("codeclone/surfaces/mcp/server.py"), "# mcp\n")
        assertEquals(temp, McpLauncher.findCodecloneMonorepoRoot(temp))
    }
}
