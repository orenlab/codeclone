"use strict";

const { spawn } = require("node:child_process");
const { EventEmitter } = require("node:events");

const { version: EXTENSION_VERSION } = require("../package.json");
const { trimTail } = require("./support");

const MCP_PROTOCOL_VERSION = "2025-03-26";
const REQUEST_TIMEOUT_MS = 5 * 60 * 1000;
const MAX_STDOUT_BUFFER_CHARS = 4 * 1024 * 1024;
const MAX_STDERR_BUFFER_CHARS = 256 * 1024;
const MAX_LOG_LINE_CHARS = 4096;

class MCPClientError extends Error {
  constructor(message) {
    super(message);
    this.name = "MCPClientError";
  }
}

class CodeCloneMcpClient extends EventEmitter {
  constructor(outputChannel) {
    super();
    this.outputChannel = outputChannel;
    this.process = null;
    this.connected = false;
    this.initialized = false;
    this.nextId = 1;
    this.pending = new Map();
    this.stdoutBuffer = "";
    this.stderrBuffer = "";
    this.diagnostics = [];
    this.launchSpec = null;
    this.serverInfo = null;
    this.toolNames = [];
    this.connectPromise = null;
    this.connectLaunchSpec = null;
  }

  isConnected() {
    return this.connected;
  }

  getConnectionSnapshot() {
    return {
      connected: this.connected,
      serverInfo: this.serverInfo ? { ...this.serverInfo } : null,
      toolNames: [...this.toolNames],
      launchSpec: this.launchSpec
        ? {
            command: this.launchSpec.command,
            args: [...this.launchSpec.args],
            cwd: this.launchSpec.cwd,
          }
        : null,
    };
  }

  async connect(launchSpec) {
    if (this._sameLaunchSpec(launchSpec, this.launchSpec) && this.connected) {
      return this._connectionResult();
    }
    if (this.connectPromise) {
      if (this._sameLaunchSpec(launchSpec, this.connectLaunchSpec)) {
        return this.connectPromise;
      }
      try {
        await this.connectPromise;
      } catch {
        // Ignore the previous attempt here; the new launch spec gets its own try.
      }
      if (this._sameLaunchSpec(launchSpec, this.launchSpec) && this.connected) {
        return this._connectionResult();
      }
    }
    const attempt = this._connectInternal(launchSpec);
    this.connectPromise = attempt;
    this.connectLaunchSpec = { ...launchSpec };
    try {
      return await attempt;
    } finally {
      if (this.connectPromise === attempt) {
        this.connectPromise = null;
        this.connectLaunchSpec = null;
      }
    }
  }

  async _connectInternal(launchSpec) {
    if (this.process !== null || this.connected || this.initialized) {
      await this.dispose({ emitState: false });
    }
    await this._spawn(launchSpec);
    try {
      const initializeResult = await this.request("initialize", {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: {
          name: "CodeClone VS Code",
          version: EXTENSION_VERSION,
        },
      });
      this._write({
        jsonrpc: "2.0",
        method: "notifications/initialized",
        params: {},
      });
      const toolsResult = await this.request("tools/list", {});
      this.connected = true;
      this.initialized = true;
      this.serverInfo = initializeResult.serverInfo || null;
      this.toolNames = Array.isArray(toolsResult.tools)
        ? toolsResult.tools.map((tool) => String(tool.name))
        : [];
      this.emit("state", {
        connected: true,
        serverInfo: this.serverInfo,
        toolNames: [...this.toolNames],
        launchSpec: this.getConnectionSnapshot().launchSpec,
      });
      return this._connectionResult();
    } catch (error) {
      await this.dispose({ emitState: false });
      throw error;
    }
  }

  async callTool(name, args = {}) {
    if (!this.connected) {
      throw new MCPClientError("CodeClone MCP is not connected.");
    }
    const result = await this.request("tools/call", {
      name,
      arguments: args,
    });
    if (result && result.isError) {
      throw new MCPClientError(
        `Tool ${name} returned an error response from CodeClone MCP.`
      );
    }
    if (result && result.structuredContent !== undefined) {
      return result.structuredContent;
    }
    if (Array.isArray(result?.content)) {
      const textChunk = result.content.find(
        (entry) => entry && entry.type === "text" && typeof entry.text === "string"
      );
      if (textChunk && typeof textChunk.text === "string") {
        try {
          return JSON.parse(textChunk.text);
        } catch {
          return { text: textChunk.text };
        }
      }
    }
    return result;
  }

  async dispose(options = {}) {
    const emitState = options.emitState !== false;
    this.connectPromise = null;
    this.connectLaunchSpec = null;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(new MCPClientError("CodeClone MCP connection closed."));
    }
    this.pending.clear();
    this.stdoutBuffer = "";
    this.stderrBuffer = "";
    this.diagnostics = [];
    this.connected = false;
    this.initialized = false;
    this.serverInfo = null;
    this.toolNames = [];
    this.launchSpec = null;
    if (this.process) {
      const child = this.process;
      this.process = null;
      child.removeAllListeners();
      child.stdout?.removeAllListeners();
      child.stderr?.removeAllListeners();
      child.kill();
    }
    if (emitState) {
      this.emit("state", { connected: false, launchSpec: null });
    }
  }

  request(method, params) {
    if (this.process === null) {
      return Promise.reject(
        new MCPClientError("CodeClone MCP process is not running.")
      );
    }
    const id = this.nextId++;
    const payload = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    };
    this._write(payload);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(
          new MCPClientError(
            `Timed out waiting for CodeClone MCP response to ${method}.`
          )
        );
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer, method });
    });
  }

  async _spawn(launchSpec) {
    await new Promise((resolve, reject) => {
      const child = spawn(launchSpec.command, launchSpec.args, {
        cwd: launchSpec.cwd,
        env: process.env,
        shell: false,
        stdio: ["pipe", "pipe", "pipe"],
      });
      this.process = child;
      this.launchSpec = { ...launchSpec };
      child.once("error", (error) => {
        reject(
          new MCPClientError(
            `Failed to start CodeClone MCP (${launchSpec.command}): ${error.message}`
          )
        );
      });
      child.once("spawn", () => {
        this.outputChannel.appendLine(
          `[codeclone] MCP spawned: ${launchSpec.command} ${launchSpec.args.join(
            " "
          )}`.trim()
        );
        resolve(undefined);
      });
      child.on("exit", (code, signal) => {
        this.outputChannel.appendLine(
          `[codeclone] MCP exited (code=${code ?? "null"}, signal=${signal ?? "null"})`
        );
        const wasConnected = this.connected;
        for (const pending of this.pending.values()) {
          clearTimeout(pending.timer);
          pending.reject(new MCPClientError(this._buildExitMessage()));
        }
        this.pending.clear();
        this.process = null;
        this.connected = false;
        this.initialized = false;
        this.serverInfo = null;
        this.toolNames = [];
        this.launchSpec = null;
        this.emit("state", { connected: false, launchSpec: null });
        if (wasConnected) {
          this.emit("exit");
        }
      });
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", (chunk) => this._handleStdout(chunk));
      child.stderr.on("data", (chunk) => this._handleStderr(chunk));
    });
  }

  _handleStdout(chunk) {
    this.stdoutBuffer = this._appendBoundedChunk(
      this.stdoutBuffer,
      chunk,
      MAX_STDOUT_BUFFER_CHARS,
      "stdout"
    );
    const lines = this.stdoutBuffer.split(/\r?\n/);
    this.stdoutBuffer = lines.pop() || "";
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        continue;
      }
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        this.outputChannel.appendLine(
          `[codeclone] stdout: ${trimTail(line, MAX_LOG_LINE_CHARS)}`
        );
        continue;
      }
      if (
        Object.prototype.hasOwnProperty.call(message, "id") &&
        (Object.prototype.hasOwnProperty.call(message, "result") ||
          Object.prototype.hasOwnProperty.call(message, "error"))
      ) {
        const pending = this.pending.get(message.id);
        if (!pending) {
          continue;
        }
        clearTimeout(pending.timer);
        this.pending.delete(message.id);
        if (message.error) {
          pending.reject(
            new MCPClientError(
              this._formatRpcError(message.error, pending.method)
            )
          );
        } else {
          pending.resolve(message.result);
        }
        continue;
      }
      if (
        message.method === "notifications/message" &&
        message.params &&
        typeof message.params.data === "string"
      ) {
        this.outputChannel.appendLine(
          `[codeclone] ${message.params.level || "info"}: ${message.params.data}`
        );
      }
    }
  }

  _handleStderr(chunk) {
    this.stderrBuffer = this._appendBoundedChunk(
      this.stderrBuffer,
      chunk,
      MAX_STDERR_BUFFER_CHARS,
      "stderr"
    );
    const lines = this.stderrBuffer.split(/\r?\n/);
    this.stderrBuffer = lines.pop() || "";
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (line) {
        this._rememberDiagnostic(line);
        this.outputChannel.appendLine(
          `[codeclone] stderr: ${trimTail(line, MAX_LOG_LINE_CHARS)}`
        );
      }
    }
  }

  _write(payload) {
    if (!this.process || !this.process.stdin.writable) {
      throw new MCPClientError("CodeClone MCP stdin is not writable.");
    }
    this.process.stdin.write(`${JSON.stringify(payload)}\n`);
  }

  _formatRpcError(error, method) {
    if (error && typeof error.message === "string") {
      return `CodeClone MCP ${method} failed: ${error.message}`;
    }
    return `CodeClone MCP ${method} failed.`;
  }

  _buildExitMessage() {
    if (this.diagnostics.length > 0) {
      return `CodeClone MCP process exited. ${this.diagnostics[this.diagnostics.length - 1]}`;
    }
    return "CodeClone MCP process exited.";
  }

  _rememberDiagnostic(line) {
    this.diagnostics.push(trimTail(line, MAX_LOG_LINE_CHARS));
    if (this.diagnostics.length > 10) {
      this.diagnostics.shift();
    }
  }

  _appendBoundedChunk(current, chunk, maxChars, streamName) {
    const combined = `${current}${chunk}`;
    if (combined.length <= maxChars) {
      return combined;
    }
    const truncated = trimTail(combined, maxChars);
    this._rememberDiagnostic(
      `CodeClone MCP ${streamName} buffer exceeded ${maxChars} characters and was truncated.`
    );
    this.outputChannel.appendLine(
      `[codeclone] ${streamName} buffer exceeded ${maxChars} characters; keeping the most recent output.`
    );
    return truncated;
  }

  _sameLaunchSpec(left, right) {
    if (!left || !right) {
      return false;
    }
    return (
      left.command === right.command &&
      left.cwd === right.cwd &&
      JSON.stringify(left.args) === JSON.stringify(right.args)
    );
  }

  _connectionResult() {
    return {
      serverInfo: this.serverInfo,
      toolNames: [...this.toolNames],
    };
  }
}

module.exports = {
  CodeCloneMcpClient,
  MCPClientError,
};
