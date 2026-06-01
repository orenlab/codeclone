"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {computeGovernanceProof} = require("../src/memoryGovernance");
const {extractToolErrorMessage} = require("../src/mcpClient");

test("extractToolErrorMessage parses FastMCP tool errors", () => {
    const result = {
        isError: true,
        content: [
            {
                type: "text",
                text: "Error executing tool manage_engineering_memory: Cannot approve record in status 'active'",
            },
        ],
    };
    assert.equal(
        extractToolErrorMessage(result, "manage_engineering_memory"),
        "Cannot approve record in status 'active'"
    );
});

test("computeGovernanceProof is stable for fixed inputs", () => {
    const key = "ab".repeat(32);
    const proof = computeGovernanceProof(key, {
        protocol: 2,
        ticketId: "ticket",
        recordId: "mem-1",
        decision: "approve",
        confirmationNonce: "nonce",
        projectId: "proj",
        statementDigest: "digest",
    });
    assert.match(proof, /^[0-9a-f]{64}$/);
    assert.equal(
        proof,
        computeGovernanceProof(key, {
            protocol: 2,
            ticketId: "ticket",
            recordId: "mem-1",
            decision: "approve",
            confirmationNonce: "nonce",
            projectId: "proj",
            statementDigest: "digest",
        })
    );
});
