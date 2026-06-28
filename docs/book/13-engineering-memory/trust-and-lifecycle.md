## Trust boundaries

```mermaid
flowchart LR
    subgraph AgentCan["Agent (MCP)"]
        R[Read ranked memory]
        D[Write draft candidates]
        V[Validate claims text]
        P[Propose from receipt]
    end

    subgraph HumanCI["Human / CI"]
        I[memory init / refresh CLI]
        A[approve / reject / archive<br/>VS Code or CLI --i-know-what-im-doing]
    end

    subgraph McpSync["MCP sync (policy-gated)"]
        B[auto bootstrap on get_relevant_memory]
        RF[refresh_from_run explicit]
    end

subgraph Never["Never via MCP"]
X1[Expand edit scope]
X2[Override findings]
X3[Mutate baselines / cache / reports]
X4[Promote draft → active without human]
end

AgentCan --> Store[(Memory DB)]
HumanCI --> Store
McpSync -->|ingest system records|Store
Never -.->|blocked|Store
```

| Action                                  | Who                                                         | Resulting status                           |
|-----------------------------------------|-------------------------------------------------------------|--------------------------------------------|
| Init / refresh ingest                   | Human or CI (`codeclone memory init`)                       | `active` system records                    |
| Auto bootstrap / refresh from MCP run   | MCP when `mcp_sync_policy` allows                           | `active` system records (same ingest path) |
| `refresh_from_run`                      | Agent MCP (explicit)                                        | Force ingest from selected MCP run         |
| `record_candidate`                      | Agent MCP                                                   | `draft`                                    |
| `finish(propose_memory=true)` on accept | Agent MCP                                                   | `draft` proposals + staleness side effects |
| `approve`                               | Human CLI (`--i-know-what-im-doing`) or VS Code IDE channel | `active` + `verified`/`supported`          |
| `reject`                                | Human CLI (`--i-know-what-im-doing`) or VS Code IDE channel | `rejected`                                 |
| `archive`                               | Human CLI (`--i-know-what-im-doing`) or VS Code IDE channel | `archived`                                 |
| Refresh detects drift                   | System on `init --refresh`                                  | `stale`                                    |
| Patch touches linked path               | System on accepted finish                                   | `stale`                                    |

---

## Record lifecycle

```mermaid
stateDiagram-v2
    [*] --> draft: agent record_candidate\nfinish propose_memory
    [*] --> active: init ingest\nhuman approve
    draft --> active: human approve
    draft --> rejected: human reject
    active --> stale: refresh drift\nscope files changed
    stale --> active: refresh reactivation\nhuman re-approve
    active --> archived: human archive
    stale --> archived: vacuum retention
    rejected --> archived: vacuum retention
    draft --> archived: vacuum retention
```

**Confidence** (`inferred` → `supported` → `verified`) and **origin**
(`system`, `agent`, `human`) are separate axes. Agents must treat `draft` and
`inferred` as non-authoritative.

Default retrieval excludes `stale`. It also filters unapproved `inferred`
records from normal visibility; inferred records become visible only after
human approval records the supporting authority. Keyword `search` excludes
`draft` unless `include_drafts=true`; scoped `get_relevant_memory` and
`for_path` / `for_symbol` include draft agent notes automatically so handoffs
are visible. Draft and inferred records remain non-authoritative until human
governance promotes them.

---
