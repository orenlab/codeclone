<!-- doc-scope: MCP session architecture. class: guide max-lines: 130 -->

# MCP architecture

## Where MCP fits

MCP is an **integration surface**, not a second analyzer. It composes over the
same canonical pipeline and report contracts as the CLI and HTML report.

```mermaid
graph LR
    A[Source Code] --> B[Core Pipeline]
    B --> C[Canonical Report]
    C --> D[CLI]
    C --> E[HTML]
    C --> F[MCP]
    C --> G[SARIF]
    style F stroke: #6366f1, stroke-width: 2px
```

## Session architecture

Every `codeclone-mcp` process owns an isolated session. Session state lives
entirely in process memory and does not survive restart.

```mermaid
graph TD
    subgraph MCPSession["MCPSession (in-memory)"]
        RS[Run Store<br/>bounded history]
        AI[Active Intents<br/>change control]
        RM[Review Markers<br/>session-local]
        BRC[Blast Radius Cache]
        GR[Gate Results]
    end

    subgraph Disk["Disk (coordination + optional sidecars)"]
        WIR["Workspace Intent Registry<br/>.codeclone/intents/ or intents.sqlite3"]
        MEM["Engineering Memory SQLite<br/>.codeclone/memory/"]
        AUD["Audit trail (optional)<br/>.codeclone/db/"]
        OBS["Platform Observability (dev-only)<br/>platform_observability.sqlite3"]
    end

    MCPSession -->|" coordination + drafts "| Disk
    MCPSession -->|" never writes "| BL[Baselines]
    MCPSession -->|" never writes "| CA["Analysis cache (.codeclone/cache.json)"]
    MCPSession -->|" never writes "| RP[Canonical reports]
    MCPSession -->|" never writes "| SC[Source Files]
    style BL fill: #fee2e2
    style CA fill: #fee2e2
    style RP fill: #fee2e2
    style SC fill: #fee2e2
```

**Read-only contract (analysis truth):** MCP never mutates source files,
baselines, analysis cache, or canonical report artifacts. It **may** write
ephemeral workspace intent records, Engineering Memory **drafts** (human approve
required for promotion), optional audit evidence, and opt-in development
telemetry when enabled. Platform Observability remains separate from repository
findings, reports, gates, baselines, and memory facts.

## Mixin chain

`MCPSession` is composed from focused mixins (`codeclone/surfaces/mcp/session.py`).
In Python MRO, the **first** listed mixin wins method resolution — workflow tools
sit outermost.

```mermaid
graph BT
    STM["_MCPSessionStateMixin<br/><small>runs, markers, gates, observability query</small>"]
    INS["_MCPSessionInsightsMixin<br/><small>session stats, audit queries</small>"]
    BR["_MCPSessionBlastRadiusMixin"]
    MM["_MCPSessionMemoryMixin"]
    IM["_MCPSessionIntentMixin"]
    PC["_MCPSessionPatchContractMixin"]
    RR["_MCPSessionReviewReceiptMixin"]
    CG["_MCPSessionClaimGuardMixin"]
    WF["_MCPSessionWorkflowMixin<br/><small>start/finish orchestration</small>"]
    S["MCPSession"]
    STM --> INS --> BR --> MM --> IM --> PC --> RR --> CG --> WF --> S
    style S stroke: #6366f1, stroke-width: 2px
    style WF fill: #eff6ff
    style MM fill: #ecfdf5
```

New capabilities extend the chain by adding a mixin **before** `MCPSession` in
the class definition — not by editing lower layers.

---
