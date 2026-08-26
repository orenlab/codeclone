"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {CodeCloneMcpClient, MCPClientError} = require("../src/mcpClient");

function outputChannelStub() {
    const lines = [];
    const warnings = [];
    return {
        lines,
        warnings,
        appendLine(line) {
            lines.push(String(line));
        },
        warn(line) {
            warnings.push(String(line));
        },
    };
}

test("bounded stream append truncates oversized buffers and records a diagnostic", () => {
    const outputChannel = outputChannelStub();
    const client = new CodeCloneMcpClient(outputChannel);

    const result = client._appendBoundedChunk("abc", "defgh", 5, "stdout");

    assert.equal(result, "defgh");
    assert.equal(client.diagnostics.length, 1);
    assert.match(client.diagnostics[0], /stdout buffer exceeded 5 characters/);
    assert.equal(outputChannel.warnings.length, 1);
    assert.match(outputChannel.warnings[0], /stdout buffer exceeded 5 characters/);
});

test("diagnostic history stays bounded", () => {
    const client = new CodeCloneMcpClient(outputChannelStub());

    for (let index = 0; index < 12; index += 1) {
        client._rememberDiagnostic(`diagnostic-${index}`);
    }

    assert.equal(client.diagnostics.length, 10);
    assert.equal(client.diagnostics[0], "diagnostic-2");
    assert.equal(client.diagnostics[9], "diagnostic-11");
});

test("diagnostics trim very long lines to the supported maximum", () => {
    const client = new CodeCloneMcpClient(outputChannelStub());
    const veryLongLine = "x".repeat(5000);

    client._rememberDiagnostic(`prefix:${veryLongLine}`);

    assert.equal(client.diagnostics.length, 1);
    assert.equal(client.diagnostics[0].length, 4096);
});

test("warning-level MCP messages map to warn logs", () => {
    const outputChannel = outputChannelStub();
    const client = new CodeCloneMcpClient(outputChannel);

    client._handleStdout(
        JSON.stringify({
            jsonrpc: "2.0",
            method: "notifications/message",
            params: {
                level: "warning",
                data: "coverage join ignored",
            },
        }) + "\n"
    );

    assert.equal(outputChannel.warnings.length, 1);
    assert.match(outputChannel.warnings[0], /coverage join ignored/);
});

test("concurrent connect calls with the same launch spec share one in-flight connection", async () => {
    const client = new CodeCloneMcpClient(outputChannelStub());
    const launchSpec = {command: "codeclone-mcp", args: [], cwd: "/tmp/workspace"};
    let spawnCalls = 0;
    const requestMethods = [];

    client._spawn = async (spec) => {
        spawnCalls += 1;
        client.process = /** @type {any} */ ({});
        client.launchSpec = {...spec};
    };
    client.request = async (method) => {
        requestMethods.push(method);
        if (method === "initialize") {
            await new Promise((resolve) => setTimeout(resolve, 5));
            return {serverInfo: {name: "CodeClone MCP"}};
        }
        if (method === "tools/list") {
            return {tools: [{name: "analyze_repository"}]};
        }
        throw new Error(`Unexpected method ${method}`);
    };
    client._write = () => {
    };

    const [first, second] = await Promise.all([
        client.connect(launchSpec),
        client.connect(launchSpec),
    ]);

    assert.equal(spawnCalls, 1);
    assert.deepEqual(requestMethods, ["initialize", "tools/list"]);
    assert.deepEqual(first, second);
    assert.equal(client.isConnected(), true);
});

// --- MCP tool-result representation precedence -------------------------------
// The MCP tool result carries the same payload twice: `structuredContent` is the
// machine representation and `content[].text` is a rendering of it. The client
// contract is that `structuredContent` wins and `content[].text` is only a
// fallback (plus the error-detail channel).
//
// Every fixture below is deliberately NOT self-consistent: the two
// representations disagree. A self-consistent fixture passes whether the client
// reads the payload or recomputes it from the rendering, so it cannot pin
// precedence at all.

function connectedClientReturning(toolResult) {
    const client = new CodeCloneMcpClient(outputChannelStub());
    client.connected = true;
    client.request = async (method) => {
        assert.equal(method, "tools/call");
        return toolResult;
    };
    return client;
}

test("tool results are read from structuredContent, not from a divergent content[].text", async () => {
    const client = connectedClientReturning({
        structuredContent: {run_id: "structured", health: {score: 90}},
        content: [
            {
                type: "text",
                text: JSON.stringify({run_id: "text-fallback", health: {score: 42}}),
            },
        ],
    });

    const payload = await client.callTool("analyze_repository", {});

    assert.deepEqual(payload, {run_id: "structured", health: {score: 90}});
    assert.notDeepEqual(payload, {run_id: "text-fallback", health: {score: 42}});
    assert.equal(payload.health.score, 90);
});

test("an empty structuredContent still wins over a populated content[].text", async () => {
    const client = connectedClientReturning({
        structuredContent: {},
        content: [
            {type: "text", text: JSON.stringify({findings: ["text-fallback"]})},
        ],
    });

    const payload = await client.callTool("list_findings", {});

    assert.deepEqual(payload, {});
});

test("tool results fall back to parsed content[].text when structuredContent is absent", async () => {
    const client = connectedClientReturning({
        content: [{type: "text", text: JSON.stringify({run_id: "text-fallback"})}],
    });

    const payload = await client.callTool("get_run_summary", {});

    assert.deepEqual(payload, {run_id: "text-fallback"});
});

test("tool errors still take their detail from content[].text", async () => {
    const client = connectedClientReturning({
        isError: true,
        structuredContent: {ok: true},
        content: [
            {
                type: "text",
                text: "Error executing tool check_clones: baseline is not trusted",
            },
        ],
    });

    await assert.rejects(
        () => client.callTool("check_clones", {}),
        (error) => {
            assert.ok(error instanceof MCPClientError);
            assert.match(error.message, /check_clones/);
            assert.match(error.message, /baseline is not trusted/);
            return true;
        }
    );
});
