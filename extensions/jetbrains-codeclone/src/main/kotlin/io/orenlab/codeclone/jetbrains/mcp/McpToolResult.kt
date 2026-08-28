package io.orenlab.codeclone.jetbrains.mcp

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive

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

/**
 * Decode the JSON-RPC `id` of an MCP response frame.
 *
 * Reads the id with `kotlinx.serialization.json`'s own [intOrNull], the reader the
 * rest of this plugin already uses. A private `JsonPrimitive.intOrNull` shadow —
 * `content.toIntOrNull()` — is not that reader: it drops `4e1`, drops a padded
 * `" 42 "`, and accepts `"+42"`, so the same frame would correlate differently here
 * than everywhere else. A non-primitive id still throws, and the caller logs and
 * drops the line, as before.
 *
 * This lives outside [McpClient] so the contract can be pinned without the
 * IntelliJ platform, and so there is exactly one decode of the response id.
 */
internal fun decodeResponseId(message: JsonObject): Int? =
    message["id"]?.jsonPrimitive?.intOrNull
