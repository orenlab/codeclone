package io.orenlab.codeclone.jetbrains.mcp

import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.util.SystemInfo
import io.orenlab.codeclone.jetbrains.CodeCloneConstants
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.exists
import kotlin.io.path.isRegularFile

object McpLauncher {
    private val LOG = Logger.getInstance(McpLauncher::class.java)

    fun resolve(workspaceRoot: Path, configuredCommand: String, configuredArgs: List<String>): McpLaunchPlan {
        if (configuredCommand.isNotBlank() && configuredCommand != "auto") {
            return McpLaunchPlan(
                normalized(
                    command = configuredCommand,
                    args = configuredArgs,
                    cwd = workspaceRoot,
                    source = "settings",
                ),
            )
        }
        for (candidate in workspaceLocalCandidates(workspaceRoot)) {
            if (candidate.exists() && candidate.isRegularFile()) {
                return McpLaunchPlan(
                    normalized(
                        command = candidate.toString(),
                        args = configuredArgs,
                        cwd = workspaceRoot,
                        source = "workspace-venv",
                    ),
                )
            }
        }
        for (candidate in toolPathCandidates("codeclone-mcp")) {
            if (candidate.isRegularFile()) {
                return McpLaunchPlan(
                    normalized(
                        command = candidate.toString(),
                        args = configuredArgs,
                        cwd = workspaceRoot,
                        source = "tool-path",
                    ),
                )
            }
        }
        val monorepoFallback = monorepoUvFallback(workspaceRoot, configuredArgs)
        val pathPrimary = normalized(
            command = "codeclone-mcp",
            args = configuredArgs,
            cwd = workspaceRoot,
            source = "path",
        )
        if (monorepoFallback != null) {
            return McpLaunchPlan(primary = pathPrimary, fallback = monorepoFallback)
        }
        if (commandOnPath("codeclone-mcp")) {
            return McpLaunchPlan(pathPrimary)
        }
        throw McpClientException(
            "codeclone-mcp launcher not found. Install with: uv tool install \"codeclone[mcp]\" " +
                "or open Settings → Tools → CodeClone and set MCP command to an absolute path " +
                "(for example .venv/bin/codeclone-mcp).",
        )
    }

    fun withIdeGovernanceChannel(args: List<String>): List<String> {
        val next = args.toMutableList()
        next.remove("--no-ide-governance-channel")
        if (!next.contains("--ide-governance-channel")) {
            next.add("--ide-governance-channel")
        }
        return next
    }

    fun spawnEnvironment(workspaceRoot: Path): Map<String, String> {
        val allowed = mutableMapOf<String, String>()
        val exact = setOf(
            "PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
            "SystemRoot", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE",
            "TZ", "TERM", "PWD", "OS", "COMSPEC", "PATHEXT",
        )
        val prefixes = listOf("CODECLONE_", "PYTHON", "UV_", "VIRTUAL_ENV", "POETRY_")
        for ((key, value) in System.getenv()) {
            if (value.isNullOrBlank()) continue
            if (exact.contains(key) || prefixes.any { key.startsWith(it) }) {
                allowed[key] = value
            }
        }
        allowed["PATH"] = augmentedPathString(allowed["PATH"])
        if (!allowed.containsKey("CODECLONE_WORKSPACE_ROOT")) {
            allowed["CODECLONE_WORKSPACE_ROOT"] = workspaceRoot.toString()
        }
        return allowed
    }

    fun toCommandLine(spec: McpLaunchSpec): GeneralCommandLine =
        GeneralCommandLine(spec.command)
            .withParameters(spec.args)
            .withWorkDirectory(spec.cwd)
            .withEnvironment(spawnEnvironment(Path.of(spec.cwd)))

    internal fun looksLikeCodeCloneRepo(root: Path): Boolean {
        if (!root.resolve("pyproject.toml").exists()) {
            return false
        }
        return root.resolve("codeclone").resolve("surfaces").resolve("mcp").resolve("server.py").exists() ||
            root.resolve("codeclone").resolve("mcp_server.py").exists() ||
            root.resolve("codeclone").resolve("main.py").exists()
    }

    internal fun findCodecloneMonorepoRoot(workspaceRoot: Path): Path? {
        var current = workspaceRoot.toAbsolutePath().normalize()
        repeat(6) {
            if (looksLikeCodeCloneRepo(current)) {
                return current
            }
            current = current.parent ?: return null
        }
        return null
    }

    private fun normalized(
        command: String,
        args: List<String>,
        cwd: Path,
        source: String,
    ): McpLaunchSpec {
        val trimmedCommand = command.trim()
        if (trimmedCommand.isEmpty()) {
            throw McpClientException("CodeClone MCP launcher command must not be empty.")
        }
        if (hasPathSeparator(trimmedCommand) && !Path.of(trimmedCommand).isAbsolute) {
            throw McpClientException(
                "Configured CodeClone launcher must be an absolute path or a bare command name.",
            )
        }
        val userArgs = args.map { it.trim() }.filter { it.isNotEmpty() }
        for (arg in userArgs) {
            val head = arg.substringBefore('=')
            if (CodeCloneConstants.BLOCKED_MCP_ARGS.contains(head)) {
                throw McpClientException(
                    "CodeClone MCP argument $arg is not allowed in the JetBrains plugin.",
                )
            }
        }
        val governanceArgs = withIdeGovernanceChannel(userArgs)
        val finalArgs = governanceArgs + listOf("--transport", "stdio")
        val resolvedCommand = lockResolvedCommand(trimmedCommand)
        return McpLaunchSpec(
            command = resolvedCommand,
            args = finalArgs,
            cwd = cwd.toString(),
            source = source,
        )
    }

    private fun workspaceLocalCandidates(root: Path): List<Path> {
        val scripts = if (SystemInfo.isWindows) "Scripts" else "bin"
        return listOf(
            root.resolve(".venv").resolve(scripts).resolve("codeclone-mcp"),
            root.resolve("venv").resolve(scripts).resolve("codeclone-mcp"),
        )
    }

    private fun monorepoUvFallback(workspaceRoot: Path, configuredArgs: List<String>): McpLaunchSpec? {
        val codecloneRoot = findCodecloneMonorepoRoot(workspaceRoot) ?: return null
        val uv = resolveExecutable("uv") ?: return null
        LOG.info("Using monorepo uv fallback for CodeClone MCP at $codecloneRoot")
        return normalized(
            command = uv,
            args = listOf("run", "--project", codecloneRoot.toString(), "codeclone-mcp"),
            cwd = workspaceRoot,
            source = "monorepo-uv",
        )
    }

    private fun resolveExecutable(name: String): String? {
        for (candidate in toolPathCandidates(name)) {
            if (candidate.isRegularFile() && Files.isExecutable(candidate)) {
                return candidate.toString()
            }
        }
        if (commandOnPath(name)) {
            return name
        }
        return null
    }

    private fun toolPathCandidates(executable: String): List<Path> {
        val names = if (SystemInfo.isWindows) {
            listOf("$executable.exe", "$executable.cmd", executable)
        } else {
            listOf(executable)
        }
        return names.flatMap { name -> augmentedPathDirectories().map { it.resolve(name) } }
    }

    private fun augmentedPathDirectories(): List<Path> {
        val seen = linkedSetOf<String>()
        val ordered = mutableListOf<Path>()
        fun add(path: String?) {
            val trimmed = path?.trim().orEmpty()
            if (trimmed.isEmpty() || !seen.add(trimmed)) {
                return
            }
            ordered.add(Path.of(trimmed))
        }
        System.getenv("PATH")?.split(if (SystemInfo.isWindows) ";" else ":")?.forEach(::add)
        homeDirectory()?.let { home ->
            add(home.resolve(".local").resolve("bin").toString())
            add(home.resolve(".cargo").resolve("bin").toString())
        }
        if (SystemInfo.isMac) {
            add("/opt/homebrew/bin")
            add("/usr/local/bin")
        }
        return ordered
    }

    private fun augmentedPathString(existingPath: String?): String =
        augmentedPathDirectories().joinToString(if (SystemInfo.isWindows) ";" else ":") { it.toString() }

    private fun homeDirectory(): Path? =
        System.getenv("HOME")?.takeIf { it.isNotBlank() }?.let { Path.of(it) }

    private fun commandOnPath(command: String): Boolean =
        try {
            val builder = ProcessBuilder(command, "--help")
            val env = builder.environment()
            spawnEnvironment(Path.of(".")).forEach { (key, value) -> env[key] = value }
            builder.redirectErrorStream(true).start().waitFor() in 0..255
        } catch (_: Exception) {
            false
        }

    private fun hasPathSeparator(value: String): Boolean =
        value.contains('/') || value.contains('\\')

    private fun lockResolvedCommand(command: String): String {
        if (!Path.of(command).isAbsolute) return command
        return try {
            val real = Path.of(command).toRealPath()
            if (!Files.isRegularFile(real)) {
                throw McpClientException("Resolved launcher is not a regular file: $real")
            }
            real.toString()
        } catch (error: McpClientException) {
            throw error
        } catch (_: Exception) {
            command
        }
    }
}
