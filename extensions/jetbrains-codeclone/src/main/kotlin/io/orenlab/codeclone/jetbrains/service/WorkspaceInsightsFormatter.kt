package io.orenlab.codeclone.jetbrains.service

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

object WorkspaceInsightsFormatter {
    fun formatProductionTriageMarkdown(state: WorkspaceRunState, workspaceName: String): String {
        val triage = state.triage
            ?: return "# CodeClone Production Triage\n\n_No triage data — run workspace analysis first._"
        val summary = state.summary ?: state.runSummary
        val baseline = summary?.get("baseline")?.jsonObject
        val health = summary?.get("health")?.jsonObject ?: triage["health"]?.jsonObject
        val findings = summary?.get("findings")?.jsonObject
        val triageFindings = triage["findings"]?.jsonObject
        val topHotspots = triage["top_hotspots"]?.jsonObject
        val topSuggestions = triage["top_suggestions"]?.jsonObject
        val focus = capitalize(triage["focus"]?.jsonPrimitive?.content?.replace('_', ' ') ?: "production")
        val healthScope = capitalize(
            summary?.get("health_scope")?.jsonPrimitive?.content
                ?: triage["health_scope"]?.jsonPrimitive?.content
                ?: "repository",
        ).replace('_', ' ')
        val hotspotItems = topHotspots?.get("items")?.jsonArray ?: JsonArray(emptyList())
        val suggestionItems = topSuggestions?.get("items")?.jsonArray ?: JsonArray(emptyList())

        return buildString {
            appendLine("# CodeClone Production Triage")
            appendLine()
            appendLine("- Run: `${state.runId ?: triage["run_id"]?.jsonPrimitive?.content ?: "n/a"}`")
            appendLine("- Workspace: **$workspaceName**")
            appendLine(
                "- Health: ${health?.get("score")?.jsonPrimitive?.intOrNull ?: state.healthScore ?: 0}/" +
                    "${health?.get("grade")?.jsonPrimitive?.content ?: state.healthGrade ?: "?"} · $healthScope scope",
            )
            baseline?.let { appendLine("- Baseline: ${formatBaselineState(it)}") }
            appendLine(
                "- Focus: $focus · ${triageFindings?.get("outside_focus")?.jsonPrimitive?.intOrNull ?: 0} outside focus",
            )
            appendLine(
                "- Findings: ${findings?.get("total")?.jsonPrimitive?.intOrNull ?: triageFindings?.get("total")?.jsonPrimitive?.intOrNull ?: 0} total",
            )
            findings?.get("production")?.jsonPrimitive?.intOrNull?.let {
                appendLine("- Production findings: $it")
            }
            findings?.get("new_by_source_kind")?.jsonObject?.let {
                appendLine("- New findings: ${formatSourceKindSummary(it)}")
            }
            triageFindings?.get("by_source_kind")?.jsonObject?.let {
                appendLine("- Source kinds: ${formatSourceKindSummary(it)}")
            }
            appendLine()
            appendLine("## Top production hotspots")
            appendLine()
            if (hotspotItems.isEmpty()) {
                appendLine("None.")
            } else {
                for (element in hotspotItems) {
                    val item = element.jsonObject
                    appendLine(
                        "- `${item["id"]?.jsonPrimitive?.content ?: "?"}` — " +
                            "${item["kind"]?.jsonPrimitive?.content ?: "unknown"} · " +
                            "${item["severity"]?.jsonPrimitive?.content ?: "unknown"} · " +
                            "${item["scope"]?.jsonPrimitive?.content ?: "unknown"} · " +
                            "priority ${item["priority"]?.jsonPrimitive?.content ?: "?"}",
                    )
                }
            }
            appendLine()
            appendLine("## Top suggestions")
            appendLine()
            if (suggestionItems.isEmpty()) {
                appendLine("None.")
            } else {
                for (element in suggestionItems) {
                    val item = element.jsonObject
                    appendLine(
                        "- `${item["id"]?.jsonPrimitive?.content ?: "?"}` — " +
                            "${item["summary"]?.jsonPrimitive?.content ?: "Suggestion"}",
                    )
                }
            }
        }
    }

    fun formatRemediationMarkdown(payload: JsonObject): String {
        val remediation = payload["remediation"]?.jsonObject ?: return "# Remediation\n\n_No remediation guidance available._"
        val findingId = payload["finding_id"]?.jsonPrimitive?.content ?: "unknown"
        val steps = remediation["steps"]?.jsonArray ?: JsonArray(emptyList())
        return buildString {
            appendLine("# Remediation: `$findingId`")
            appendLine()
            remediation["shape"]?.jsonPrimitive?.content?.let {
                appendLine(it)
                appendLine()
            }
            appendLine("- Effort: ${remediation["effort"]?.jsonPrimitive?.content ?: "unknown"}")
            appendLine("- Risk: ${remediation["risk"]?.jsonPrimitive?.content ?: "unknown"}")
            remediation["why_now"]?.jsonPrimitive?.content?.let {
                appendLine()
                appendLine("Why now: $it")
            }
            if (steps.isNotEmpty()) {
                appendLine()
                appendLine("## Steps")
                for (element in steps) {
                    appendLine("- ${element.jsonPrimitive.content}")
                }
            }
        }
    }

    fun formatSessionStatsMarkdown(payload: JsonObject, workspaceName: String): String {
        val workspace = payload["workspace"]?.jsonObject
        val counts = payload["counts"]?.jsonObject
        val latest = payload["latest_run"]?.jsonObject
        val audit = payload["audit"]?.jsonObject
        val agents = payload["agents"]?.jsonArray ?: JsonArray(emptyList())
        val workflows = payload["top_workflows"]?.jsonArray ?: JsonArray(emptyList())
        val footprint = payload["token_footprint"]?.jsonObject

        return buildString {
            appendLine("# Workspace Session Stats")
            appendLine()
            appendLine("Workspace: **$workspaceName**")
            workspace?.get("root")?.jsonPrimitive?.content?.let {
                appendLine("Root: `$it`")
            }
            appendLine()
            appendLine("## Summary")
            appendLine("- Workspace health: ${workspace?.get("health")?.jsonPrimitive?.content ?: "unknown"}")
            appendLine("- Live agents: ${counts?.get("live_agents")?.jsonPrimitive?.intOrNull ?: 0}")
            appendLine("- Active intents: ${counts?.get("active_intents")?.jsonPrimitive?.intOrNull ?: 0}")
            appendLine("- Visible intents: ${counts?.get("visible_intents")?.jsonPrimitive?.intOrNull ?: 0}")
            appendLine(
                "- Stale / expired / recoverable: " +
                        "${counts?.get("stale")?.jsonPrimitive?.intOrNull ?: 0} / " +
                        "${counts?.get("expired")?.jsonPrimitive?.intOrNull ?: 0} / " +
                        "${counts?.get("recoverable")?.jsonPrimitive?.intOrNull ?: 0}",
            )
            workspace?.get("intent_registry_backend")?.jsonPrimitive?.content?.let { backend ->
                val storage = workspace["intent_registry_storage"]?.jsonPrimitive?.content ?: "—"
                appendLine("- Intent registry: $backend ($storage)")
            }
            if (audit?.get("enabled")?.jsonPrimitive?.content == "true") {
                appendLine("- Audit storage: ${audit["storage"]?.jsonPrimitive?.content ?: "enabled"}")
            }
            appendLine()
            appendLine("## Latest cached run")
            if (latest?.get("cache_present")?.jsonPrimitive?.content == "true" &&
                latest["run_id"]?.jsonPrimitive?.content != null
            ) {
                appendLine("- Run: `${latest["run_id"]?.jsonPrimitive?.content}`")
                latest["age_seconds"]?.jsonPrimitive?.intOrNull?.let { appendLine("- Age: ${formatAgeSeconds(it)}") }
                latest["health"]?.jsonPrimitive?.content?.let { appendLine("- Health: $it") }
                latest["findings"]?.jsonPrimitive?.content?.let { appendLine("- Findings: $it") }
                latest["files"]?.jsonPrimitive?.content?.let { appendLine("- Files indexed: $it") }
            } else {
                appendLine("_No cached report in .codeclone/report.json._")
            }
            appendLine()
            appendLiveAgents(agents)
            appendWorkflows(workflows)
            appendFootprint(footprint)
            appendLine()
            appendLine("_IDE-only MCP tool — requires `--ide-governance-channel` launcher._")
        }
    }

    fun formatAuditTrailMarkdown(payload: JsonObject, workspaceName: String): String {
        val status = payload["status"]?.jsonPrimitive?.content ?: "ok"
        val message = payload["message"]?.jsonPrimitive?.content
        val database = payload["database"]?.jsonObject
        val counts = payload["counts"]?.jsonObject
        val timeRange = payload["time_range"]?.jsonObject
        val tokenSummary = payload["token_summary"]?.jsonObject
        val footprint = payload["payload_footprint"]?.jsonObject
        val events = payload["events"]?.jsonArray ?: JsonArray(emptyList())

        return buildString {
            appendLine("# Controller Audit Trail")
            appendLine()
            appendLine("Workspace: **$workspaceName**")
            appendLine()
            if (status != "ok") {
                appendLine("**Status:** $status${message?.let { " — $it" } ?: ""}")
                appendLine()
            }
            appendLine("## Database")
            database?.get("path")?.jsonPrimitive?.content?.let { appendLine("- Path: `$it`") }
            database?.get("size_bytes")?.jsonPrimitive?.intOrNull?.let {
                appendLine("- Size: ${formatBytes(it)}")
            }
            database?.get("retention_days")?.jsonPrimitive?.intOrNull?.let {
                appendLine("- Retention: $it days")
            }
            appendLine()
            appendLine("## Counts")
            appendLine("- Total events: ${counts?.get("total_events")?.jsonPrimitive?.intOrNull ?: 0}")
            appendLine(
                "- By kind: intents ${counts?.get("intent_events")?.jsonPrimitive?.intOrNull ?: 0} · " +
                        "contracts ${counts?.get("contract_events")?.jsonPrimitive?.intOrNull ?: 0} · " +
                        "receipts ${counts?.get("receipt_events")?.jsonPrimitive?.intOrNull ?: 0} · " +
                        "violations ${counts?.get("violation_events")?.jsonPrimitive?.intOrNull ?: 0}",
            )
            if (timeRange?.get("oldest_event_utc") != null || timeRange?.get("latest_event_utc") != null) {
                appendLine(
                    "- Time range: ${timeRange["oldest_event_utc"]?.jsonPrimitive?.content ?: "—"} → " +
                            "${timeRange["latest_event_utc"]?.jsonPrimitive?.content ?: "—"}",
                )
            }
            tokenSummary?.get("total_estimated_tokens")?.jsonPrimitive?.intOrNull?.let { tokens ->
                appendLine(
                    "- Token estimate: ~$tokens " +
                            "(${tokenSummary["token_encoding"]?.jsonPrimitive?.content ?: "unknown"}, " +
                            "${tokenSummary["token_event_count"]?.jsonPrimitive?.intOrNull ?: 0} events)",
                )
            }
            appendFootprintSection(footprint)
            appendLine()
            appendLine("## Recent events (${events.size})")
            if (events.isEmpty()) {
                appendLine("_No recent events in this window._")
            } else {
                for (element in events) {
                    val event = element.jsonObject
                    appendLine(
                        "- **${event["summary"]?.jsonPrimitive?.content ?: event["event_type"]?.jsonPrimitive?.content ?: "event"}** " +
                                "(${event["event_type"]?.jsonPrimitive?.content ?: ""})",
                    )
                    val meta = listOfNotNull(
                        event["created_at_utc"]?.jsonPrimitive?.content,
                        event["severity"]?.jsonPrimitive?.content,
                        event["intent_id"]?.jsonPrimitive?.content?.let { "`$it`" },
                        event["agent_label"]?.jsonPrimitive?.content,
                        event["estimated_tokens"]?.jsonPrimitive?.intOrNull?.let { "~$it tok" },
                    ).joinToString(" · ")
                    if (meta.isNotBlank()) appendLine("  $meta")
                }
            }
            appendLine()
            appendLine("_IDE-only MCP tool — requires `--ide-governance-channel` launcher._")
        }
    }

    private fun StringBuilder.appendLiveAgents(agents: JsonArray) {
        val live = agents.mapNotNull { it.jsonObject }.filter { agent ->
            agent["alive"]?.jsonPrimitive?.content == "true"
        }
        appendLine("## Live agents")
        if (live.isEmpty()) {
            appendLine("_No live agent processes with visible intents._")
            appendLine()
            return
        }
        for (agent in live) {
            appendLine(
                "### PID ${agent["pid"]?.jsonPrimitive?.content ?: "?"} · " +
                        "${agent["label"]?.jsonPrimitive?.content ?: "unknown"}",
            )
            val intents = agent["intents"]?.jsonArray ?: JsonArray(emptyList())
            for (element in intents) {
                val intent = element.jsonObject
                appendLine(
                    "- `${intent["intent_id"]?.jsonPrimitive?.content ?: ""}` · " +
                            "${intent["status"]?.jsonPrimitive?.content ?: ""} · " +
                            "scope ${intent["scope_file_count"]?.jsonPrimitive?.intOrNull ?: 0} files · " +
                            "lease ${formatDurationSeconds(intent["lease_remaining_seconds"]?.jsonPrimitive?.intOrNull ?: 0)}",
                )
            }
            appendLine()
        }
    }

    private fun StringBuilder.appendWorkflows(workflows: JsonArray) {
        if (workflows.isEmpty()) return
        appendLine("## Top workflows (audit footprint)")
        for (element in workflows) {
            val wf = element.jsonObject
            val name = "${wf["workflow_kind"]?.jsonPrimitive?.content ?: "workflow"}:" +
                    "${wf["workflow_id"]?.jsonPrimitive?.content ?: "-"}"
            val tokens = wf["tokens"]?.jsonPrimitive?.intOrNull ?: wf["total_tokens"]?.jsonPrimitive?.intOrNull ?: 0
            val calls = wf["calls"]?.jsonPrimitive?.intOrNull ?: wf["call_count"]?.jsonPrimitive?.intOrNull ?: 0
            appendLine("- $name · ~$tokens tokens · $calls calls · ${wf["agent_label"]?.jsonPrimitive?.content ?: "—"}")
        }
        appendLine()
    }

    private fun StringBuilder.appendFootprint(footprint: JsonObject?) {
        if (footprint == null) return
        val totalTokens = footprint["total_tokens"]?.jsonPrimitive?.intOrNull ?: return
        appendLine("## Token footprint")
        appendLine("- Total tokens: ~$totalTokens")
        footprint["tool_calls"]?.jsonPrimitive?.intOrNull?.let { appendLine("- Tool calls: $it") }
        footprint["encoding"]?.jsonPrimitive?.content?.let { appendLine("- Encoding: $it") }
        appendLine()
    }

    private fun StringBuilder.appendFootprintSection(footprint: JsonObject?) {
        if (footprint == null || footprint.isEmpty()) return
        appendLine()
        appendLine("## Payload footprint (retention window)")
        footprint["total_tokens"]?.jsonPrimitive?.intOrNull?.let { appendLine("- Total tokens: ~$it") }
        footprint["tool_calls"]?.jsonPrimitive?.intOrNull?.let { appendLine("- Tool calls: $it") }
        val top = footprint["top_workflows"]?.jsonArray ?: JsonArray(emptyList())
        for (element in top) {
            val wf = element.jsonObject
            val tokens = wf["tokens"]?.jsonPrimitive?.intOrNull ?: wf["total_tokens"]?.jsonPrimitive?.intOrNull ?: 0
            val calls = wf["calls"]?.jsonPrimitive?.intOrNull ?: wf["call_count"]?.jsonPrimitive?.intOrNull ?: 0
            appendLine(
                "- ${wf["workflow_kind"]?.jsonPrimitive?.content ?: "workflow"}:" +
                        "${wf["workflow_id"]?.jsonPrimitive?.content ?: "-"} · ~$tokens tokens · $calls calls",
            )
        }
    }

    internal fun formatAgeSeconds(seconds: Int): String {
        if (seconds < 0) return "unknown"
        if (seconds < 60) return "${seconds}s ago"
        val minutes = seconds / 60
        if (minutes < 60) return "${minutes}m ago"
        val hours = minutes / 60
        val remainingMinutes = minutes % 60
        return if (remainingMinutes > 0) "${hours}h${remainingMinutes}m ago" else "${hours}h ago"
    }

    internal fun formatDurationSeconds(seconds: Int): String {
        if (seconds <= 0) return "expired"
        if (seconds < 60) return "${seconds}s"
        val minutes = seconds / 60
        val remaining = seconds % 60
        return if (remaining > 0) "${minutes}m${remaining}s" else "${minutes}m"
    }

    internal fun formatBytes(bytes: Int): String {
        if (bytes < 1024) return "$bytes B"
        var value = bytes.toDouble() / 1024.0
        val units = arrayOf("KB", "MB", "GB", "TB")
        var unitIndex = 0
        while (value >= 1024 && unitIndex < units.lastIndex) {
            value /= 1024.0
            unitIndex++
        }
        val rounded = if (value >= 10) value.toInt() else (value * 10).toInt() / 10.0
        return "$rounded ${units[unitIndex]}"
    }

    internal fun formatSourceKindSummary(obj: JsonObject?): String {
        if (obj == null || obj.isEmpty()) return "none"
        return obj.entries.sortedBy { it.key }.joinToString(" · ") { (key, value) ->
            "$key: ${value.jsonPrimitive.content}"
        }
    }

    private fun formatBaselineState(baseline: JsonObject): String {
        val status = baseline["status"]?.jsonPrimitive?.content ?: "unknown"
        val trusted = baseline["trusted"]?.jsonPrimitive?.content
        return if (trusted != null) "$status (trusted=$trusted)" else status
    }

    private fun capitalize(value: String): String =
        value.trim().replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }
}
