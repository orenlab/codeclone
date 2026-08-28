package io.orenlab.codeclone.jetbrains.memory

import io.orenlab.codeclone.jetbrains.CodeCloneConstants
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class MemoryGovernanceTest {
    @Test
    fun `computeGovernanceProof is stable for fixed inputs`() {
        val key = "ab".repeat(32)
        val proof = MemoryGovernance.computeGovernanceProof(
            keyHex = key,
            protocol = CodeCloneConstants.IDE_GOVERNANCE_PROTOCOL,
            ticketId = "ticket",
            recordId = "mem-1",
            decision = "approve",
            confirmationNonce = "nonce",
            projectId = "proj",
            statementDigest = "digest",
        )
        assertTrue(proof.matches(Regex("^[0-9a-f]{64}$")))
        assertEquals(
            proof,
            MemoryGovernance.computeGovernanceProof(
                keyHex = key,
                protocol = CodeCloneConstants.IDE_GOVERNANCE_PROTOCOL,
                ticketId = "ticket",
                recordId = "mem-1",
                decision = "approve",
                confirmationNonce = "nonce",
                projectId = "proj",
                statementDigest = "digest",
            ),
        )
    }
}
