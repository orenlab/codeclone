"use strict";

const crypto = require("node:crypto");

const {version: EXTENSION_VERSION} = require("../package.json");
const {
    GOVERNANCE_TOOL_TIMEOUT_MS,
    MCPClientError,
} = require("./mcpClient");

const GOVERNANCE_SECRET_KEY = "codeclone.ideGovernanceKey";
const IDE_CLIENT_NAME = "CodeClone VS Code";
const IDE_GOVERNANCE_PROTOCOL = 2;

/**
 * @param {string[]} args
 * @returns {string[]}
 */
function withIdeGovernanceChannel(args) {
    const next = Array.isArray(args) ? [...args] : [];
    const disableIndex = next.indexOf("--no-ide-governance-channel");
    if (disableIndex !== -1) {
        next.splice(disableIndex, 1);
    }
    if (!next.includes("--ide-governance-channel")) {
        next.push("--ide-governance-channel");
    }
    return next;
}

/**
 * @param {import("vscode").SecretStorage} secrets
 * @returns {Promise<string>}
 */
async function ensureGovernanceKey(secrets) {
    let key = await secrets.get(GOVERNANCE_SECRET_KEY);
    if (!key || key.length < 64) {
        key = crypto.randomBytes(32).toString("hex");
        await secrets.store(GOVERNANCE_SECRET_KEY, key);
    }
    return key;
}

/**
 * @param {object} fields
 * @returns {string}
 */
function computeGovernanceProof(keyHex, fields) {
    const key = Buffer.from(keyHex, "hex");
    const message =
        `v${fields.protocol}|${fields.ticketId}|${fields.recordId}|${fields.decision}|` +
        `${fields.confirmationNonce}|${fields.projectId}|${fields.statementDigest}`;
    return crypto.createHmac("sha256", key).update(message, "utf8").digest("hex");
}

/**
 * @param {import("./mcpClient").CodeCloneMcpClient} client
 * @param {import("vscode").ExtensionContext} context
 * @param {string} root
 */
async function registerIdeGovernance(client, context, root) {
    const key = await ensureGovernanceKey(context.secrets);
    return client.callTool(
        "manage_engineering_memory",
        {
            root,
            action: "register_ide_governance",
            ide_governance_key: key,
            client_name: IDE_CLIENT_NAME,
            client_version: EXTENSION_VERSION,
        },
        {
            timeoutMs: GOVERNANCE_TOOL_TIMEOUT_MS,
            timeoutLabel: "Register IDE governance",
        }
    );
}

/**
 * @param {import("./mcpClient").CodeCloneMcpClient} client
 * @param {import("vscode").ExtensionContext} context
 * @param {string} root
 */
async function ensureIdeGovernanceRegistered(client, context, root) {
    const result = await registerIdeGovernance(client, context, root);
    if (result.status === "ok") {
        return result;
    }
    if (result.status === "rejected") {
        const nextStep = result.next_step ? ` ${result.next_step}` : "";
        throw new MCPClientError(
            `${result.message || "IDE governance is not available."}${nextStep}`
        );
    }
    throw new MCPClientError(
        `Could not register IDE governance (status: ${String(result.status)}).`
    );
}

/**
 * @param {import("./mcpClient").CodeCloneMcpClient} client
 * @param {string} root
 * @param {string} recordId
 * @param {"approve"|"reject"|"archive"} decision
 */
async function prepareGovernance(client, root, recordId, decision) {
    return client.callTool(
        "manage_engineering_memory",
        {
            root,
            action: "prepare_governance",
            record_id: recordId,
            decision,
        },
        {
            timeoutMs: GOVERNANCE_TOOL_TIMEOUT_MS,
            timeoutLabel: "Prepare memory governance",
        }
    );
}

/**
 * @param {import("./mcpClient").CodeCloneMcpClient} client
 * @param {import("vscode").ExtensionContext} context
 * @param {object} prepared
 * @param {string} root
 * @param {string} actor
 * @param {"approve"|"reject"|"archive"} decision
 */
async function commitGovernance(
    client,
    context,
    prepared,
    root,
    actor,
    decision
) {
    const key = await ensureGovernanceKey(context.secrets);
    const ticketId = String(prepared.governance_ticket || "");
    const recordId = String(prepared.record?.id || "");
    const confirmationNonce = String(prepared.confirmation_nonce || "");
    const projectId = String(prepared.project_id || "");
    const statementDigest = String(prepared.statement_digest || "");
    const proof = computeGovernanceProof(key, {
        protocol: IDE_GOVERNANCE_PROTOCOL,
        ticketId,
        recordId,
        decision,
        confirmationNonce,
        projectId,
        statementDigest,
    });
    return client.callTool(
        "manage_engineering_memory",
        {
            root,
            action: "commit_governance",
            record_id: recordId,
            decision,
            governance_ticket: ticketId,
            confirmation_nonce: confirmationNonce,
            proof,
            actor,
            protocol: IDE_GOVERNANCE_PROTOCOL,
        },
        {
            timeoutMs: GOVERNANCE_TOOL_TIMEOUT_MS,
            timeoutLabel: "Commit memory governance",
        }
    );
}

module.exports = {
    IDE_CLIENT_NAME,
    IDE_GOVERNANCE_PROTOCOL,
    GOVERNANCE_TOOL_TIMEOUT_MS,
    withIdeGovernanceChannel,
    ensureGovernanceKey,
    computeGovernanceProof,
    registerIdeGovernance,
    ensureIdeGovernanceRegistered,
    prepareGovernance,
    commitGovernance,
};
