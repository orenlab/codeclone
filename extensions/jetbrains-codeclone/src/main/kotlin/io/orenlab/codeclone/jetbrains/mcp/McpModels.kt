package io.orenlab.codeclone.jetbrains.mcp

class McpClientException(message: String, cause: Throwable? = null) : Exception(message, cause)

data class McpLaunchSpec(
    val command: String,
    val args: List<String>,
    val cwd: String,
    val source: String = "",
)

data class McpLaunchPlan(
    val primary: McpLaunchSpec,
    val fallback: McpLaunchSpec? = null,
)

data class McpConnectionSnapshot(
    val connected: Boolean,
    val serverName: String? = null,
    val serverVersion: String? = null,
    val toolNames: List<String> = emptyList(),
    val launchSpec: McpLaunchSpec? = null,
)
