"use strict";

const {safeArray, safeObject} = require("./formatters");
const {recordStatement} = require("./memoryController");

/**
 * @param {object} semantic
 */
function formatSemanticStatusLine(semantic) {
    const block = safeObject(semantic);
    if (!block || Object.keys(block).length === 0) {
        return "Semantic recall: off";
    }
    if (block.used) {
        const provider = block.provider || block.backend || "provider";
        const model = block.model ? ` · ${block.model}` : "";
        return `Semantic recall: on (${provider}${model})`;
    }
    const reason = block.reason || "unavailable";
    return `Semantic recall: off (${reason})`;
}

/**
 * @param {string} recordId
 */
function memoryRecordCommandUri(recordId) {
    const encoded = encodeURIComponent(JSON.stringify([recordId]));
    return `command:codeclone.openMemoryRecordById?${encoded}`;
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/**
 * @param {object} record
 */
function recordCardHtml(record) {
    const item = safeObject(record);
    const id = String(item.id || "");
    if (!id) {
        return "";
    }
    const type = escapeHtml(item.type || "memory");
    const status = escapeHtml(item.status || "unknown");
    const confidence = escapeHtml(item.confidence || "—");
    const statement = escapeHtml(recordStatement(item));
    const subjects = safeArray(item.subjects)
        .map((raw) => {
            const subject = safeObject(raw);
            const key = escapeHtml(subject.subject_key || "");
            const kind = escapeHtml(subject.subject_kind || "subject");
            return `<li><code>${key}</code> <span class="muted">(${kind})</span></li>`;
        })
        .join("");
    const openHref = memoryRecordCommandUri(id);
    const truncated = item.statement_truncated ? " · truncated preview" : "";
    return [
        '<article class="record-card">',
        '<div class="record-head">',
        `<span class="pill pill-type">${type}</span>`,
        `<span class="pill pill-status">${status}</span>`,
        `<span class="pill pill-confidence">${confidence}</span>`,
        "</div>",
        `<p class="statement">${statement}</p>`,
        subjects ? `<ul class="subjects">${subjects}</ul>` : "",
        `<p class="record-meta"><code>${escapeHtml(id)}</code>${escapeHtml(truncated)}</p>`,
        `<p class="record-actions"><a class="action-link" href="${openHref}">Open full record</a></p>`,
        "</article>",
    ].join("");
}

/**
 * @param {object[]} auditEvents
 */
function auditEventsSection(auditEvents) {
    if (auditEvents.length === 0) {
        return "";
    }
    const items = auditEvents
        .slice(0, 8)
        .map((raw) => {
            const event = safeObject(raw);
            const summary = escapeHtml(
                String(event.summary || event.event_type || event.kind || "audit event")
            );
            const path = event.path ? `<code>${escapeHtml(event.path)}</code>` : "";
            return `<li>${summary}${path ? ` · ${path}` : ""}</li>`;
        })
        .join("");
    return [
        '<section class="audit-callout" aria-label="Semantic audit incidents">',
        "<h2>Semantic audit incidents</h2>",
        '<p class="muted">Typed separately from memory records — review before trusting semantic hits.</p>',
        `<ul>${items}</ul>`,
        "</section>",
    ].join("");
}

/**
 * @param {object} params
 */
function renderMemorySearchHtml(params) {
    const query = String(params.query || "");
    const workspaceName = String(params.workspaceName || "workspace");
    const nonce = String(params.nonce || "0");
    const result = safeObject(params.result);
    const response = safeObject(result.response);
    const payload = safeObject(response.payload);
    const records = safeArray(payload.records);
    const truncated = Boolean(payload.truncated);
    const recordCount = Number(payload.record_count ?? records.length);
    const semantic = safeObject(response.semantic);
    const semanticLine = formatSemanticStatusLine(semantic);
    const mode = escapeHtml(String(response.mode || "search"));
    const detailLevel = escapeHtml(String(response.detail_level || "compact"));
    const auditEvents = safeArray(payload.audit_events);
    const policy = safeObject(payload.retrieval_policy);
    const policyDrafts = policy.drafts_included ? "drafts included" : "drafts excluded";

    const cards =
        records.length > 0
            ? records.map((record) => recordCardHtml(record)).join("\n")
            : '<p class="empty">No records matched this query with the current filters.</p>';

    return [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">',
        `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">`,
        `<style nonce="${nonce}">`,
        "body{font-family:var(--vscode-font-family);color:var(--vscode-editor-foreground);background:var(--vscode-editor-background);padding:16px 22px;line-height:1.5;margin:0}",
        ".header{margin-bottom:12px}",
        "h1{font-size:1.35em;margin:0 0 4px}",
        "h2{font-size:1.05em;margin:18px 0 8px}",
        ".meta{color:var(--vscode-descriptionForeground);font-size:.9em}",
        ".meta span{margin-right:14px}",
        ".banner{margin:12px 0;padding:10px 12px;border-radius:6px;background:var(--vscode-textBlockQuote-background);border-left:3px solid var(--vscode-textLink-foreground)}",
        ".audit-callout{margin:16px 0;padding:10px 12px;border-radius:6px;border:1px solid var(--vscode-inputValidation-warningBorder);background:var(--vscode-inputValidation-warningBackground)}",
        ".record-card{margin:14px 0;padding:12px 14px;border:1px solid var(--vscode-widget-border,#444);border-radius:8px}",
        ".record-head{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}",
        ".pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.78em;font-weight:600;text-transform:uppercase;letter-spacing:.02em;background:var(--vscode-badge-background);color:var(--vscode-badge-foreground)}",
        ".pill-status{background:var(--vscode-charts-blue,#1e90ff)}",
        ".statement{margin:6px 0;white-space:pre-wrap}",
        ".subjects{margin:6px 0 0 18px;padding:0;font-size:.9em}",
        ".record-meta,.record-actions{font-size:.85em;color:var(--vscode-descriptionForeground)}",
        ".action-link{color:var(--vscode-textLink-foreground);text-decoration:none}",
        ".action-link:hover{text-decoration:underline}",
        ".muted{color:var(--vscode-descriptionForeground)}",
        ".empty{color:var(--vscode-descriptionForeground);font-style:italic}",
        "code{font-family:var(--vscode-editor-font-family)}",
        "</style>",
        "</head>",
        "<body>",
        '<header class="header">',
        "<h1>Engineering Memory Search</h1>",
        `<p class="meta"><span>Workspace: ${escapeHtml(workspaceName)}</span>`,
        `<span>Mode: ${mode}</span>`,
        `<span>Detail: ${detailLevel}</span>`,
        `<span>${escapeHtml(policyDrafts)}</span></p>`,
        `<p class="meta"><span>Query: <strong>${escapeHtml(query)}</strong></span>`,
        `<span>${recordCount} record${recordCount === 1 ? "" : "s"}${truncated ? " (truncated)" : ""}</span></p>`,
        "</header>",
        `<div class="banner" role="status">${escapeHtml(semanticLine)}</div>`,
        auditEventsSection(auditEvents),
        `<section aria-label="Search results">${cards}</section>`,
        '<footer class="meta"><p>Use the panel title bar <strong>Refresh</strong> or command palette filters. Open records via trusted command links only.</p></footer>',
        "</body>",
        "</html>",
    ].join("\n");
}

module.exports = {
    escapeHtml,
    renderMemorySearchHtml,
    recordCardHtml,
};
