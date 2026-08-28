package io.orenlab.codeclone.jetbrains

object CodeCloneConstants {
    const val PLUGIN_VERSION = "0.3.9"
    const val IDE_CLIENT_NAME = "CodeClone JetBrains"
    const val MINIMUM_SERVER_VERSION = "2.0.0"
    const val MCP_PROTOCOL_VERSION = "2025-03-26"
    const val REQUEST_TIMEOUT_MS = 5 * 60 * 1000L
    const val GOVERNANCE_TOOL_TIMEOUT_MS = 90_000L
    const val GOVERNANCE_SECRET_KEY = "codeclone.ideGovernanceKey"
    const val IDE_GOVERNANCE_PROTOCOL = 2

    val BLOCKED_MCP_ARGS = setOf(
        "--transport",
        "--host",
        "--port",
        "--allow-remote",
        "--json-response",
        "--stateless-http",
    )
}
