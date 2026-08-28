package io.orenlab.codeclone.jetbrains.memory

import com.intellij.credentialStore.CredentialAttributes
import com.intellij.credentialStore.Credentials
import com.intellij.credentialStore.generateServiceName
import com.intellij.ide.passwordSafe.PasswordSafe
import io.orenlab.codeclone.jetbrains.CodeCloneConstants
import io.orenlab.codeclone.jetbrains.mcp.McpClient
import io.orenlab.codeclone.jetbrains.mcp.McpClientException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object MemoryGovernance {
    private val random = SecureRandom()

    suspend fun ensureIdeGovernanceRegistered(client: McpClient, root: String) {
        if (!client.hasTool("manage_engineering_memory")) return
        val result = registerIdeGovernance(client, root).jsonObject
        when (result["status"]?.jsonPrimitive?.content) {
            "ok" -> return
            "rejected" -> {
                val nextStep = result["next_step"]?.jsonPrimitive?.content?.trim().orEmpty()
                val message = result["message"]?.jsonPrimitive?.content
                    ?: "IDE governance is not available."
                throw McpClientException(
                    if (nextStep.isNotEmpty()) "$message $nextStep" else message,
                )
            }

            else -> throw McpClientException(
                "Could not register IDE governance (status: ${result["status"]?.jsonPrimitive?.content ?: "unknown"}).",
            )
        }
    }

    suspend fun registerIdeGovernance(client: McpClient, root: String): JsonObject {
        if (!client.hasTool("manage_engineering_memory")) {
            return buildJsonObject { put("status", "skipped") }
        }
        val key = ensureGovernanceKey()
        return client.callTool(
            "manage_engineering_memory",
            buildJsonObject {
                put("root", root)
                put("action", "register_ide_governance")
                put("ide_governance_key", key)
                put("client_name", CodeCloneConstants.IDE_CLIENT_NAME)
                put("client_version", CodeCloneConstants.PLUGIN_VERSION)
            },
            timeoutMs = CodeCloneConstants.GOVERNANCE_TOOL_TIMEOUT_MS,
        ).jsonObject
    }

    suspend fun approveRecord(client: McpClient, root: String, recordId: String, actor: String) {
        commitDecision(client, root, recordId, "approve", actor)
    }

    suspend fun rejectRecord(client: McpClient, root: String, recordId: String, actor: String) {
        commitDecision(client, root, recordId, "reject", actor)
    }

    private suspend fun commitDecision(
        client: McpClient,
        root: String,
        recordId: String,
        decision: String,
        actor: String,
    ) {
        val prepared = prepareGovernance(client, root, recordId, decision)
        val key = ensureGovernanceKey()
        val proof = computeGovernanceProof(
            keyHex = key,
            protocol = CodeCloneConstants.IDE_GOVERNANCE_PROTOCOL,
            ticketId = prepared.ticketId,
            recordId = prepared.recordId,
            decision = decision,
            confirmationNonce = prepared.confirmationNonce,
            projectId = prepared.projectId,
            statementDigest = prepared.statementDigest,
        )
        val committed = client.callTool(
            "manage_engineering_memory",
            buildJsonObject {
                put("root", root)
                put("action", "commit_governance")
                put("record_id", prepared.recordId)
                put("decision", decision)
                put("governance_ticket", prepared.ticketId)
                put("confirmation_nonce", prepared.confirmationNonce)
                put("proof", proof)
                put("actor", actor)
                put("protocol", CodeCloneConstants.IDE_GOVERNANCE_PROTOCOL)
            },
            timeoutMs = CodeCloneConstants.GOVERNANCE_TOOL_TIMEOUT_MS,
        ).jsonObject
        when (committed["status"]?.jsonPrimitive?.content) {
            "ok" -> return
            "rejected", "error" -> {
                val message = committed["message"]?.jsonPrimitive?.content ?: "Memory governance commit failed."
                throw McpClientException(message)
            }

            else -> throw McpClientException(
                "Memory governance commit failed (status: ${committed["status"]?.jsonPrimitive?.content ?: "unknown"}).",
            )
        }
    }

    private suspend fun prepareGovernance(
        client: McpClient,
        root: String,
        recordId: String,
        decision: String,
    ): PreparedGovernance {
        val prepare = client.callTool(
            "manage_engineering_memory",
            buildJsonObject {
                put("root", root)
                put("action", "prepare_governance")
                put("record_id", recordId)
                put("decision", decision)
            },
            timeoutMs = CodeCloneConstants.GOVERNANCE_TOOL_TIMEOUT_MS,
        ).jsonObject
        when (prepare["status"]?.jsonPrimitive?.content) {
            "ok" -> Unit
            "not_found" -> throw McpClientException("Memory record not found: $recordId")
            else -> {
                val message = prepare["message"]?.jsonPrimitive?.content
                    ?: "Prepare governance failed (status: ${prepare["status"]?.jsonPrimitive?.content ?: "unknown"})."
                throw McpClientException(message)
            }
        }
        val ticketId = prepare["governance_ticket"]?.jsonPrimitive?.content
            ?: throw McpClientException("Missing governance_ticket from prepare_governance.")
        val confirmationNonce = prepare["confirmation_nonce"]?.jsonPrimitive?.content
            ?: throw McpClientException("Missing confirmation_nonce from prepare_governance.")
        val resolvedRecordId = prepare["record"]?.jsonObject?.get("id")?.jsonPrimitive?.content ?: recordId
        return PreparedGovernance(
            ticketId = ticketId,
            recordId = resolvedRecordId,
            confirmationNonce = confirmationNonce,
            projectId = prepare["project_id"]?.jsonPrimitive?.content ?: "",
            statementDigest = prepare["statement_digest"]?.jsonPrimitive?.content ?: "",
        )
    }

    internal fun computeGovernanceProof(
        keyHex: String,
        protocol: Int,
        ticketId: String,
        recordId: String,
        decision: String,
        confirmationNonce: String,
        projectId: String,
        statementDigest: String,
    ): String {
        val message =
            "v$protocol|$ticketId|$recordId|$decision|" +
                    "$confirmationNonce|$projectId|$statementDigest"
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(hexToBytes(keyHex), "HmacSHA256"))
        return mac.doFinal(message.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    }

    private fun ensureGovernanceKey(): String {
        val attributes = CredentialAttributes(
            generateServiceName("CodeClone", CodeCloneConstants.GOVERNANCE_SECRET_KEY),
        )
        val existing = PasswordSafe.instance.getPassword(attributes)
        if (!existing.isNullOrBlank() && existing.length >= 64) return existing
        val bytes = ByteArray(32)
        random.nextBytes(bytes)
        val generated = bytes.joinToString("") { "%02x".format(it) }
        PasswordSafe.instance.set(attributes, Credentials(null, generated))
        return generated
    }

    private fun hexToBytes(hex: String): ByteArray {
        require(hex.length % 2 == 0) { "governance key must be hex" }
        return ByteArray(hex.length / 2) { index ->
            hex.substring(index * 2, index * 2 + 2).toInt(16).toByte()
        }
    }

    internal data class PreparedGovernance(
        val ticketId: String,
        val recordId: String,
        val confirmationNonce: String,
        val projectId: String,
        val statementDigest: String,
    )
}
