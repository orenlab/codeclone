package io.orenlab.codeclone.jetbrains.mcp

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull

/**
 * Decode the `isError` flag of an MCP `tools/call` result.
 *
 * MCP sends `isError` as a real JSON boolean. `kotlinx.serialization.json`'s
 * own [booleanOrNull] decodes the boolean form and the quoted string form
 * alike; everything else — absent, null, an object, an array, an unrelated
 * string — is not an error.
 *
 * This lives outside [McpClient] so the contract can be pinned without the
 * IntelliJ platform, and so there is exactly one decode of `isError`.
 */
internal fun isToolErrorResult(result: JsonObject): Boolean =
    (result["isError"] as? JsonPrimitive)?.booleanOrNull == true
