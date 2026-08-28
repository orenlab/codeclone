package io.orenlab.codeclone.jetbrains.mcp

import com.intellij.execution.process.OSProcessHandler
import com.intellij.execution.process.ProcessAdapter
import com.intellij.execution.process.ProcessEvent
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.util.Key
import io.orenlab.codeclone.jetbrains.CodeCloneConstants
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.OutputStreamWriter
import java.nio.charset.StandardCharsets
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

class McpClient {
    private val LOG = Logger.getInstance(McpClient::class.java)
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    private var handler: OSProcessHandler? = null
    private var writer: OutputStreamWriter? = null
    private var launchSpec: McpLaunchSpec? = null
    private var connected = false
    private var serverName: String? = null
    private var serverVersion: String? = null
    private var toolNames: List<String> = emptyList()

    private val nextId = AtomicInteger(1)
    private val pending = ConcurrentHashMap<Int, CompletableDeferred<JsonElement>>()
    private val stdoutBuffer = StringBuilder()

    fun snapshot(): McpConnectionSnapshot =
        McpConnectionSnapshot(
            connected = connected,
            serverName = serverName,
            serverVersion = serverVersion,
            toolNames = toolNames,
            launchSpec = launchSpec,
        )

    fun isConnected(): Boolean = connected

    fun hasTool(name: String): Boolean = toolNames.contains(name)

    suspend fun connect(spec: McpLaunchSpec) = withContext(Dispatchers.IO) {
        if (connected && launchSpec == spec) return@withContext
        dispose()
        val commandLine = McpLauncher.toCommandLine(spec)
        val process = commandLine.createProcess()
        val osHandler = OSProcessHandler(process, commandLine.commandLineString, StandardCharsets.UTF_8)
        handler = osHandler
        launchSpec = spec
        writer = OutputStreamWriter(process.outputStream, StandardCharsets.UTF_8)

        osHandler.addProcessListener(object : ProcessAdapter() {
            override fun onTextAvailable(event: ProcessEvent, outputType: Key<*>) {
                if (outputType == com.intellij.execution.process.ProcessOutputTypes.STDOUT) {
                    handleStdout(event.text)
                } else if (outputType == com.intellij.execution.process.ProcessOutputTypes.STDERR) {
                    LOG.debug("codeclone-mcp stderr: ${event.text.trim()}")
                }
            }

            override fun processTerminated(event: ProcessEvent) {
                connected = false
                failPending("CodeClone MCP connection closed.")
                LOG.warn("codeclone-mcp exited with code ${event.exitCode}")
            }
        })
        osHandler.startNotify()

        val initResult = request(
            "initialize",
            buildJsonObject {
                put("protocolVersion", CodeCloneConstants.MCP_PROTOCOL_VERSION)
                put("capabilities", buildJsonObject {})
                put(
                    "clientInfo",
                    buildJsonObject {
                        put("name", CodeCloneConstants.IDE_CLIENT_NAME)
                        put("version", CodeCloneConstants.PLUGIN_VERSION)
                    },
                )
            },
        )
        notify(buildJsonObject {
            put("jsonrpc", "2.0")
            put("method", "notifications/initialized")
            put("params", buildJsonObject {})
        })
        val toolsResult = request("tools/list", buildJsonObject {})
        val serverInfo = initResult.jsonObject["serverInfo"]?.jsonObject
        serverName = serverInfo?.get("name")?.jsonPrimitive?.content
        serverVersion = serverInfo?.get("version")?.jsonPrimitive?.content
        toolNames = toolsResult.jsonObject["tools"]?.jsonArray
            ?.mapNotNull { it.jsonObject["name"]?.jsonPrimitive?.content }
            ?: emptyList()
        connected = true
        LOG.info("Connected to CodeClone MCP ($serverName $serverVersion) via ${spec.source}")
    }

    suspend fun callTool(
        name: String,
        arguments: JsonObject,
        timeoutMs: Long = CodeCloneConstants.REQUEST_TIMEOUT_MS,
    ): JsonElement = withContext(Dispatchers.IO) {
        if (!connected) throw McpClientException("CodeClone MCP is not connected.")
        val result = withTimeout(timeoutMs) {
            request(
                "tools/call",
                buildJsonObject {
                    put("name", name)
                    put("arguments", arguments)
                },
            )
        }
        val resultObject = result.jsonObject
        if (isToolErrorResult(resultObject)) {
            throw McpClientException(extractToolError(resultObject, name) ?: "Tool $name failed.")
        }
        parseToolPayload(resultObject)
    }

    fun dispose() {
        connected = false
        failPending("CodeClone MCP connection closed.")
        handler?.destroyProcess()
        handler = null
        writer = null
        launchSpec = null
        serverName = null
        serverVersion = null
        toolNames = emptyList()
        stdoutBuffer.clear()
    }

    private suspend fun request(method: String, params: JsonObject): JsonElement {
        val id = nextId.getAndIncrement()
        val deferred = CompletableDeferred<JsonElement>()
        pending[id] = deferred
        notify(
            buildJsonObject {
                put("jsonrpc", "2.0")
                put("id", id)
                put("method", method)
                put("params", params)
            },
        )
        return withTimeout(CodeCloneConstants.REQUEST_TIMEOUT_MS) {
            deferred.await()
        }
    }

    private fun notify(payload: JsonObject) {
        val line = json.encodeToString(JsonObject.serializer(), payload)
        val output = writer ?: throw McpClientException("CodeClone MCP process is not running.")
        synchronized(output) {
            output.write(line)
            output.write("\n")
            output.flush()
        }
    }

    private fun handleStdout(chunk: String) {
        stdoutBuffer.append(chunk)
        while (true) {
            val newline = stdoutBuffer.indexOf('\n')
            if (newline < 0) break
            val line = stdoutBuffer.substring(0, newline).trim()
            stdoutBuffer.delete(0, newline + 1)
            if (line.isEmpty()) continue
            try {
                dispatchLine(line)
            } catch (error: Exception) {
                LOG.debug("Failed to parse MCP line: $line", error)
            }
        }
    }

    private fun dispatchLine(line: String) {
        val message = json.parseToJsonElement(line).jsonObject
        if (message.containsKey("id") && (message.containsKey("result") || message.containsKey("error"))) {
            val id = decodeResponseId(message) ?: return
            val deferred = pending.remove(id) ?: return
            val error = message["error"]?.jsonObject
            if (error != null) {
                val text = error["message"]?.jsonPrimitive?.content ?: "Unknown MCP error"
                deferred.completeExceptionally(McpClientException(text))
            } else {
                deferred.complete(message["result"] ?: buildJsonObject {})
            }
            return
        }
        if (message["method"]?.jsonPrimitive?.content == "notifications/message") {
            val params = message["params"]?.jsonObject
            val text = params?.get("message")?.jsonPrimitive?.content
            if (!text.isNullOrBlank()) LOG.info("[codeclone-mcp] $text")
        }
    }

    private fun parseToolPayload(result: JsonObject): JsonElement {
        result["structuredContent"]?.let { return it }
        val content = result["content"]?.jsonArray ?: return result
        val textChunk = content.firstOrNull {
            it.jsonObject["type"]?.jsonPrimitive?.content == "text"
        }?.jsonObject?.get("text")?.jsonPrimitive?.content
        if (textChunk != null) {
            return try {
                json.parseToJsonElement(textChunk)
            } catch (_: Exception) {
                buildJsonObject { put("text", textChunk) }
            }
        }
        return result
    }

    private fun extractToolError(result: JsonObject, toolName: String): String? {
        val content = result["content"]?.jsonArray ?: return null
        for (entry in content) {
            val text = entry.jsonObject["text"]?.jsonPrimitive?.content?.trim() ?: continue
            val prefix = "Error executing tool $toolName:"
            return if (text.startsWith(prefix)) text.removePrefix(prefix).trim() else text
        }
        return null
    }

    private fun failPending(message: String) {
        for ((_, deferred) in pending) {
            deferred.completeExceptionally(McpClientException(message))
        }
        pending.clear()
    }
}
