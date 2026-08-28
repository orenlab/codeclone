package io.orenlab.codeclone.jetbrains.ui.render

import com.intellij.util.ui.UIUtil
import io.orenlab.codeclone.jetbrains.service.WorkspaceInsightsFormatter
import io.orenlab.codeclone.jetbrains.service.WorkspaceRunState
import io.orenlab.codeclone.jetbrains.ui.components.HtmlInsightPane
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

object WorkspaceInsightsHtmlRenderer {
    /**
     * Swing [JEditorPane] HTML/CSS supports only a small CSS subset.
     * Avoid @media, font-variant, border-radius, and other modern properties.
     */
    fun sharedStyles(): String {
        val dark = UIUtil.isUnderDarcula()
        val fg = if (dark) "#DFE1E5" else "#2B2D30"
        val bg = if (dark) "#2B2D30" else "#FFFFFF"
        val muted = if (dark) "#9DA0A8" else "#6C707E"
        val border = if (dark) "#43454A" else "#DFE1E5"
        val bannerBg = if (dark) "#393B40" else "#F2F2F2"
        val warnBg = if (dark) "#4A3F28" else "#FFF8E6"
        return """
            body { font-family: sans-serif; color: $fg; background-color: $bg; margin: 8px; line-height: 1.4; }
            h1 { font-size: 16pt; margin-top: 0; margin-bottom: 6px; }
            h2 { font-size: 13pt; margin-top: 16px; margin-bottom: 6px; }
            h3 { font-size: 11pt; margin-top: 12px; margin-bottom: 4px; }
            p { margin: 6px 0; }
            ul { margin: 6px 0 6px 18px; padding: 0; }
            .meta { color: $muted; font-size: 10pt; }
            .muted { color: $muted; font-style: italic; }
            .banner { margin: 10px 0; padding: 8px; background-color: $bannerBg; border-left: 3px solid #3574F0; }
            .banner-warn { background-color: $warnBg; border-left-color: #CCA700; }
            table { border-collapse: collapse; width: 100%; margin: 8px 0; }
            th { text-align: left; color: $muted; font-weight: bold; padding: 4px 8px 4px 0; vertical-align: top; }
            td { padding: 4px 8px 4px 0; vertical-align: top; }
            .summary-table th { width: 180px; }
            .data-table td { border-bottom: 1px solid $border; }
            .data-table .num { text-align: right; }
            .meta-cell { color: $muted; font-size: 9pt; }
            .pill { padding: 2px 8px; font-weight: bold; }
            .health-idle { color: $fg; background-color: $muted; }
            .health-clean { color: #FFFFFF; background-color: #2EA043; }
            .health-active { color: #FFFFFF; background-color: #3574F0; }
            .health-contested { color: #1E1F22; background-color: #CCA700; }
            code { font-family: monospace; font-size: 10pt; }
        """.trimIndent()
    }

    @Deprecated("Use sharedStyles()", ReplaceWith("sharedStyles()"))
    val SHARED_STYLES: String get() = sharedStyles()

    fun renderSessionStatsHtml(payload: JsonObject, workspaceName: String): String {
        val root = payload["workspace"]?.jsonObject?.get("root")?.jsonPrimitive?.content.orEmpty()
        val body = sessionStatsBody(payload)
        return htmlDocument(
            title = "Workspace Session Stats",
            subtitle = "Workspace: ${escape(workspaceName)} · mirrors <code>codeclone . --session-stats</code>",
            rootLine = root,
            body = body,
            footer = "IDE-only MCP tool — requires IDE governance channel.",
        )
    }

    fun renderAuditTrailHtml(payload: JsonObject, workspaceName: String): String {
        val body = auditTrailBody(payload)
        return htmlDocument(
            title = "Controller Audit Trail",
            subtitle = "Workspace: ${escape(workspaceName)}",
            rootLine = null,
            body = body,
            footer = "IDE-only MCP tool — requires IDE governance channel.",
        )
    }

    fun renderProductionTriageHtml(state: WorkspaceRunState, workspaceName: String): String {
        val triage = state.triage
        if (triage == null) {
            return htmlDocument(
                title = "Production Triage",
                subtitle = "Workspace: ${escape(workspaceName)}",
                rootLine = null,
                body = """<p class="muted">No triage data — run workspace analysis first.</p>""",
                footer = "Mirrors VS Code production triage view.",
            )
        }
        val summary = state.summary ?: state.runSummary
        val health = summary?.get("health")?.jsonObject ?: triage["health"]?.jsonObject
        val findings = summary?.get("findings")?.jsonObject
        val triageFindings = triage["findings"]?.jsonObject
        val focus = escape(
            (triage["focus"]?.jsonPrimitive?.content ?: "production").replace('_', ' '),
        )
        val healthScore = health?.get("score")?.jsonPrimitive?.intOrNull ?: state.healthScore ?: 0
        val healthGrade = escape(health?.get("grade")?.jsonPrimitive?.content ?: state.healthGrade ?: "?")
        val runId = escape(state.runId ?: triage["run_id"]?.jsonPrimitive?.content ?: "n/a")
        val outsideFocus = triageFindings?.get("outside_focus")?.jsonPrimitive?.intOrNull ?: 0
        val totalFindings = findings?.get("total")?.jsonPrimitive?.intOrNull
            ?: triageFindings?.get("total")?.jsonPrimitive?.intOrNull
            ?: 0

        val summaryRows = listOf(
            "Run" to """<code>$runId</code>""",
            "Health" to "$healthScore/$healthGrade",
            "Focus" to focus,
            "Outside focus" to outsideFocus.toString(),
            "Findings" to totalFindings.toString(),
            "Source kinds" to escape(
                WorkspaceInsightsFormatter.formatSourceKindSummary(triageFindings?.get("by_source_kind")?.jsonObject),
            ),
        )

        val hotspotItems = triage["top_hotspots"]?.jsonObject?.get("items")?.jsonArray ?: JsonArray(emptyList())
        val hotspotsHtml = if (hotspotItems.isEmpty()) {
            """<p class="muted">No production hotspots in triage window.</p>"""
        } else {
            buildString {
                append("""<table class="data-table"><thead><tr>""")
                append("<th>ID</th><th>Kind</th><th>Severity</th><th>Scope</th><th class=\"num\">Priority</th>")
                append("</tr></thead><tbody>")
                for (element in hotspotItems) {
                    val item = element.jsonObject
                    append("<tr>")
                    append("<td><code>").append(escape(item["id"]?.jsonPrimitive?.content ?: "?")).append("</code></td>")
                    append("<td>").append(escape(item["kind"]?.jsonPrimitive?.content ?: "—")).append("</td>")
                    append("<td>").append(escape(item["severity"]?.jsonPrimitive?.content ?: "—")).append("</td>")
                    append("<td>").append(escape(item["scope"]?.jsonPrimitive?.content ?: "—")).append("</td>")
                    append("<td class=\"num\">").append(escape(item["priority"]?.jsonPrimitive?.content ?: "—")).append("</td>")
                    append("</tr>")
                }
                append("</tbody></table>")
            }
        }

        val suggestionItems = triage["top_suggestions"]?.jsonObject?.get("items")?.jsonArray ?: JsonArray(emptyList())
        val suggestionsHtml = if (suggestionItems.isEmpty()) {
            """<p class="muted">No suggestions in triage window.</p>"""
        } else {
            buildString {
                append("<ul>")
                for (element in suggestionItems) {
                    val item = element.jsonObject
                    append("<li><code>")
                    append(escape(item["id"]?.jsonPrimitive?.content ?: "?"))
                    append("</code> — ")
                    append(escape(item["summary"]?.jsonPrimitive?.content ?: "Suggestion"))
                    append("</li>")
                }
                append("</ul>")
            }
        }

        val body = buildString {
            append(summaryTable(summaryRows))
            append("<h2>Top production hotspots</h2>")
            append(hotspotsHtml)
            append("<h2>Top suggestions</h2>")
            append(suggestionsHtml)
        }
        return htmlDocument(
            title = "Production Triage",
            subtitle = "Workspace: ${escape(workspaceName)} · production-first review",
            rootLine = state.runId,
            body = body,
            footer = "Open Hotspots tab for the full review queue.",
        )
    }

    private fun htmlDocument(
        title: String,
        subtitle: String,
        rootLine: String?,
        body: String,
        footer: String,
    ): String = buildString {
        appendLine("<!DOCTYPE html><html><head><meta charset=\"UTF-8\">")
        append("<style>").append(sharedStyles()).appendLine("</style></head><body>")
        append("<header class=\"header\"><h1>").append(escape(title)).append("</h1>")
        append("<p class=\"meta\">").append(subtitle).append("</p>")
        if (!rootLine.isNullOrBlank()) {
            append("<p class=\"meta\"><code>").append(escape(rootLine)).append("</code></p>")
        }
        append("</header>")
        append(body)
        append("<footer class=\"meta\"><p>").append(escape(footer)).append("</p></footer>")
        append("</body></html>")
    }

    private fun sessionStatsBody(payload: JsonObject): String {
        val workspace = payload["workspace"]?.jsonObject
        val counts = payload["counts"]?.jsonObject
        val latest = payload["latest_run"]?.jsonObject
        val audit = payload["audit"]?.jsonObject
        val footprint = payload["token_footprint"]?.jsonObject
        val agents = payload["agents"]?.jsonArray ?: JsonArray(emptyList())
        val workflows = payload["top_workflows"]?.jsonArray ?: JsonArray(emptyList())
        val health = workspace?.get("health")?.jsonPrimitive?.content ?: "unknown"

        val summaryRows = mutableListOf<Pair<String, String>>()
        summaryRows += "Workspace health" to """<span class="pill ${healthClass(health)}">${escape(health)}</span>"""
        summaryRows += "Live agents" to escape(counts?.get("live_agents")?.jsonPrimitive?.intOrNull?.toString() ?: "0")
        summaryRows += "Active intents" to escape(counts?.get("active_intents")?.jsonPrimitive?.intOrNull?.toString() ?: "0")
        summaryRows += "Visible intents" to escape(counts?.get("visible_intents")?.jsonPrimitive?.intOrNull?.toString() ?: "0")
        summaryRows += "Stale / expired / recoverable" to listOf("stale", "expired", "recoverable").joinToString(" / ") {
            escape(counts?.get(it)?.jsonPrimitive?.intOrNull?.toString() ?: "0")
        }
        workspace?.get("intent_registry_backend")?.jsonPrimitive?.content?.let { backend ->
            val storage = workspace["intent_registry_storage"]?.jsonPrimitive?.content ?: "—"
            summaryRows += "Intent registry" to "${escape(backend)} (${escape(storage)})"
        }
        if (audit?.get("enabled")?.jsonPrimitive?.content == "true") {
            summaryRows += "Audit storage" to escape(audit["storage"]?.jsonPrimitive?.content ?: "enabled")
        }

        val latestHtml = if (latest?.get("cache_present")?.jsonPrimitive?.content == "true" &&
            latest["run_id"]?.jsonPrimitive?.content != null
        ) {
            val parts = mutableListOf("<code>${escape(latest["run_id"]!!.jsonPrimitive.content)}</code>")
            latest["age_seconds"]?.jsonPrimitive?.intOrNull?.let {
                parts += escape(WorkspaceInsightsFormatter.formatAgeSeconds(it))
            }
            latest["health"]?.jsonPrimitive?.content?.let { parts += "health=${escape(it)}" }
            latest["findings"]?.jsonPrimitive?.content?.let { parts += "findings=${escape(it)}" }
            latest["files"]?.jsonPrimitive?.content?.let { parts += "${escape(it)} files indexed" }
            "<p>${parts.joinToString(" · ")}</p>"
        } else {
            """<p class="muted">No cached report in .codeclone/report.json.</p>"""
        }

        val liveAgents = agents.mapNotNull { it.jsonObject }.filter { it["alive"]?.jsonPrimitive?.content == "true" }
        val agentsHtml = if (liveAgents.isEmpty()) {
            """<p class="muted">No live agent processes with visible intents.</p>"""
        } else {
            liveAgents.joinToString("") { agent ->
                val intents = agent["intents"]?.jsonArray ?: JsonArray(emptyList())
                val intentRows = intents.mapNotNull { it.jsonObject }.joinToString("") { intent ->
                    val files = intent["allowed_files"]?.jsonArray?.mapNotNull { f ->
                        f.jsonPrimitive.content
                    }.orEmpty()
                    val preview = files.take(2).joinToString(", ") { "<code>${escape(it)}</code>" }
                    val extra = if (files.size > 2) " (+${files.size - 2} more)" else ""
                    """<tr>
                        <td><code>${escape(intent["intent_id"]?.jsonPrimitive?.content.orEmpty())}</code></td>
                        <td>${escape(intent["status"]?.jsonPrimitive?.content.orEmpty())}</td>
                        <td>${escape(intent["ownership"]?.jsonPrimitive?.content.orEmpty())}</td>
                        <td>${escape(intent["scope_file_count"]?.jsonPrimitive?.intOrNull?.toString() ?: "0")}</td>
                        <td>${escape(WorkspaceInsightsFormatter.formatDurationSeconds(intent["lease_remaining_seconds"]?.jsonPrimitive?.intOrNull ?: 0))}</td>
                        <td>$preview$extra</td>
                    </tr>"""
                }
                """<h3>PID ${escape(agent["pid"]?.jsonPrimitive?.content.orEmpty())} · ${escape(agent["label"]?.jsonPrimitive?.content ?: "unknown")}</h3>
                <table class="data-table"><thead><tr>
                <th>Intent</th><th>Status</th><th>Ownership</th><th>Scope</th><th>Lease</th><th>Allowed files</th>
                </tr></thead><tbody>$intentRows</tbody></table>"""
            }
        }

        val workflowsHtml = if (workflows.isEmpty()) "" else {
            val rows = workflows.mapNotNull { it.jsonObject }.joinToString("") { wf ->
                val name = "${wf["workflow_kind"]?.jsonPrimitive?.content ?: "workflow"}:" +
                    "${wf["workflow_id"]?.jsonPrimitive?.content ?: "-"}"
                val tokens = wf["tokens"]?.jsonPrimitive?.intOrNull ?: wf["total_tokens"]?.jsonPrimitive?.intOrNull ?: 0
                val calls = wf["calls"]?.jsonPrimitive?.intOrNull ?: wf["call_count"]?.jsonPrimitive?.intOrNull ?: 0
                """<tr>
                    <td>${escape(name)}</td>
                    <td class="num">~${escape(tokens.toString())}</td>
                    <td class="num">${escape(calls.toString())}</td>
                    <td>${escape(wf["agent_label"]?.jsonPrimitive?.content ?: "—")}</td>
                </tr>"""
            }
            """<h2>Top workflows (audit footprint)</h2>
            <table class="data-table"><thead><tr>
            <th>Workflow</th><th>Tokens</th><th>Calls</th><th>Agent</th>
            </tr></thead><tbody>$rows</tbody></table>"""
        }

        val footprintHtml = footprint?.get("total_tokens")?.jsonPrimitive?.intOrNull?.let { total ->
            val calls = footprint["tool_calls"]?.jsonPrimitive?.intOrNull ?: 0
            if (calls > 0) {
                """<p class="banner">~${escape(total.toString())} estimated tokens in retention (${escape(footprint["encoding"]?.jsonPrimitive?.content ?: "unknown")}, ${escape(calls.toString())} tool calls)</p>"""
            } else null
        }.orEmpty()

        return buildString {
            append(summaryTable(summaryRows))
            append(footprintHtml)
            append("<h2>Latest cached run</h2>").append(latestHtml)
            append("<h2>Live agents and intents</h2>").append(agentsHtml)
            append(workflowsHtml)
        }
    }

    private fun auditTrailBody(payload: JsonObject): String {
        val status = payload["status"]?.jsonPrimitive?.content ?: "ok"
        val message = payload["message"]?.jsonPrimitive?.content
        val database = payload["database"]?.jsonObject
        val counts = payload["counts"]?.jsonObject
        val timeRange = payload["time_range"]?.jsonObject
        val tokenSummary = payload["token_summary"]?.jsonObject
        val footprint = payload["payload_footprint"]?.jsonObject
        val events = payload["events"]?.jsonArray ?: JsonArray(emptyList())

        val banner = if (status != "ok") {
            """<div class="banner banner-warn" role="alert"><strong>${escape(status)}</strong>${message?.let { ": ${escape(it)}" } ?: ""}</div>"""
        } else ""

        val metaRows = mutableListOf<Pair<String, String>>()
        database?.get("path")?.jsonPrimitive?.content?.let {
            metaRows += "Database" to "<code>${escape(it)}</code>"
        }
        database?.get("size_bytes")?.jsonPrimitive?.intOrNull?.let {
            metaRows += "Size" to escape(WorkspaceInsightsFormatter.formatBytes(it))
        }
        database?.get("retention_days")?.jsonPrimitive?.intOrNull?.let {
            metaRows += "Retention" to "${escape(it.toString())} days"
        }
        metaRows += "Total events" to escape(counts?.get("total_events")?.jsonPrimitive?.intOrNull?.toString() ?: "0")
        metaRows += "By kind" to listOf(
            "intents" to "intent_events",
            "contracts" to "contract_events",
            "receipts" to "receipt_events",
            "violations" to "violation_events",
        ).joinToString(" · ") { (label, key) ->
            "$label ${counts?.get(key)?.jsonPrimitive?.intOrNull ?: 0}"
        }.let { escape(it) }
        if (timeRange?.get("oldest_event_utc") != null || timeRange?.get("latest_event_utc") != null) {
            metaRows += "Time range" to escape(
                "${timeRange["oldest_event_utc"]?.jsonPrimitive?.content ?: "—"} → " +
                    "${timeRange["latest_event_utc"]?.jsonPrimitive?.content ?: "—"}",
            )
        }
        tokenSummary?.get("total_estimated_tokens")?.jsonPrimitive?.intOrNull?.let { tokens ->
            metaRows += "Token estimate" to escape(
                "~$tokens (${tokenSummary["token_encoding"]?.jsonPrimitive?.content ?: "unknown"}, " +
                    "${tokenSummary["token_event_count"]?.jsonPrimitive?.intOrNull ?: 0} events)",
            )
        }

        val footprintHtml = buildString {
            if (footprint != null && footprint.isNotEmpty()) {
                append("<h2>Payload footprint (retention window)</h2>")
                footprint["total_tokens"]?.jsonPrimitive?.intOrNull?.let {
                    append("<p>Total tokens: ~${escape(it.toString())}</p>")
                }
                footprint["tool_calls"]?.jsonPrimitive?.intOrNull?.let {
                    append("<p>Tool calls: ${escape(it.toString())}</p>")
                }
                val top = footprint["top_workflows"]?.jsonArray ?: JsonArray(emptyList())
                if (top.isNotEmpty()) {
                    val rows = top.mapNotNull { it.jsonObject }.joinToString("") { wf ->
                        val tokens = wf["tokens"]?.jsonPrimitive?.intOrNull ?: wf["total_tokens"]?.jsonPrimitive?.intOrNull ?: 0
                        val calls = wf["calls"]?.jsonPrimitive?.intOrNull ?: wf["call_count"]?.jsonPrimitive?.intOrNull ?: 0
                        """<tr><td>${escape("${wf["workflow_kind"]?.jsonPrimitive?.content ?: "workflow"}:${wf["workflow_id"]?.jsonPrimitive?.content ?: "-"}")}</td>
                        <td class="num">~${escape(tokens.toString())}</td><td class="num">${escape(calls.toString())}</td></tr>"""
                    }
                    append("""<table class="data-table"><thead><tr><th>Workflow</th><th>Tokens</th><th>Calls</th></tr></thead><tbody>$rows</tbody></table>""")
                }
            }
        }

        val eventsHtml = if (events.isEmpty()) {
            """<p class="muted">No recent events in this window.</p>"""
        } else {
            val rows = events.mapNotNull { it.jsonObject }.joinToString("") { event ->
                val summary = escape(event["summary"]?.jsonPrimitive?.content ?: event["event_type"]?.jsonPrimitive?.content ?: "event")
                val meta = listOfNotNull(
                    event["created_at_utc"]?.jsonPrimitive?.content,
                    event["severity"]?.jsonPrimitive?.content,
                    event["intent_id"]?.jsonPrimitive?.content?.let { "<code>${escape(it)}</code>" },
                    event["agent_label"]?.jsonPrimitive?.content,
                ).joinToString(" · ")
                val tokens = event["estimated_tokens"]?.jsonPrimitive?.intOrNull?.let { " ~${escape(it.toString())} tok" } ?: ""
                """<tr><td>$summary</td><td>${escape(event["event_type"]?.jsonPrimitive?.content.orEmpty())}</td>
                <td class="meta-cell">$meta$tokens</td></tr>"""
            }
            """<h2>Recent events (${events.size})</h2>
            <table class="data-table events-table"><thead><tr>
            <th>Summary</th><th>Type</th><th>Details</th>
            </tr></thead><tbody>$rows</tbody></table>"""
        }

        return banner + summaryTable(metaRows) + footprintHtml + eventsHtml
    }

    private fun summaryTable(rows: List<Pair<String, String>>): String =
        """<table class="summary-table"><tbody>${rows.joinToString("") { (label, value) ->
            "<tr><th>${escape(label)}</th><td>$value</td></tr>"
        }}</tbody></table>"""

    private fun healthClass(health: String): String = when (health) {
        "idle" -> "health-idle"
        "clean" -> "health-clean"
        "contested" -> "health-contested"
        else -> "health-active"
    }

    private fun escape(text: String): String = HtmlInsightPane.escapeHtml(text)
}
