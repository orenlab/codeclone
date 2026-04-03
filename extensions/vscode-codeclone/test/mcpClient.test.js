"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { CodeCloneMcpClient } = require("../src/mcpClient");

function outputChannelStub() {
  const lines = [];
  return {
    lines,
    appendLine(line) {
      lines.push(String(line));
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
  assert.equal(outputChannel.lines.length, 1);
  assert.match(outputChannel.lines[0], /stdout buffer exceeded 5 characters/);
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
