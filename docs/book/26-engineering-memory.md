# 26. Engineering Memory

## Purpose

Engineering Memory is a **local, evidence-linked knowledge store** for a Python
repository. It captures structural facts, document links, git provenance, and
governed human/agent notes — then surfaces them to AI agents **before and during**
controlled edits.

!!! note "Not a second analyzer"
Memory reads from the same canonical report, contracts, docs, tests, and git
facts as CodeClone analysis. It does **not** run a separate LLM inference
path, mutate source files, or override structural findings.

!!! note "Not analysis cache"
The SQLite database under `.cache/codeclone/memory/` is a **governed memory
contract**, separate from analysis cache (`cache.json`) and baselines
(`codeclone.baseline.json`).

---

## Status

| Phase | Capability                                                    | Surface                                                                            |
|-------|---------------------------------------------------------------|------------------------------------------------------------------------------------|
| 18.1  | Store, init ingest, CLI `init\|status\|for-path\|search`      | CLI                                                                                |
| 18.2  | Scoped retrieval, ranking                                     | MCP `get_relevant_memory`, `query_engineering_memory`                              |
| 18.3  | Refresh staleness, scope staleness, retention                 | CLI `stale`, `vacuum`; finish hook marks scope stale                               |
| 18.4  | Draft governance, claim validation                            | MCP `manage_engineering_memory`; CLI `review-candidates\|approve\|reject\|archive` |
| 18.5  | Scope coverage, finish proposals                              | `finish_controlled_change(propose_memory=true)`                                    |
| 18.6  | FTS search (`match_mode`), git hotspots, schema 1.1, Rich CLI | CLI `--match`; MCP `filters.match_mode`                                            |
| 18.7  | MCP sync from analysis runs                                     | `mcp_sync_policy`; auto bootstrap on `get_relevant_memory`; `refresh_from_run`     |

Schema version constant: `ENGINEERING_MEMORY_SCHEMA_VERSION` in
`codeclone/contracts/__init__.py` (currently **`1.1`**).

---

## Architecture

```mermaid
graph TB
    subgraph Sources["Deterministic sources"]
        CR[Canonical Report]
        CT[Contracts / docs / tests]
        GIT[Git provenance]
        RC[Finish receipts / audit]
    end

    subgraph MemoryStore["Engineering Memory (SQLite)"]
        REC[memory_records]
        SUB[memory_subjects]
        EV[memory_evidence]
        FTS[memory_fts FTS5]
    end

    subgraph Surfaces["Read / write surfaces"]
        CLI["codeclone memory *"]
        MCP_R["MCP read tools"]
        MCP_W["MCP draft writes"]
        HUM["Human approve CLI"]
    end

    CR -->|init / refresh ingest| MemoryStore
    CT -->|init / refresh ingest| MemoryStore
    GIT -->|init / refresh ingest| MemoryStore
    RC -->|propose_from_receipt / finish hook| MemoryStore
    MemoryStore --> CLI
    MemoryStore --> MCP_R
    MCP_W -->|draft only| MemoryStore
    HUM -->|approve / reject / archive| MemoryStore
    style MemoryStore stroke: #6366f1, stroke-width: 2px
    style MCP_W fill: #fef9c3
    style HUM fill: #dcfce7
```

Module ownership:

| Module                                            | Role                                                 |
|---------------------------------------------------|------------------------------------------------------|
| `codeclone/memory/sqlite_store.py`                | SQLite persistence, FTS sync, subject dedup          |
| `codeclone/memory/ingest/*`                       | Init/refresh batch builders from report + git + docs |
| `codeclone/memory/retrieval/*`                    | Scoped ranking and query router                      |
| `codeclone/memory/governance.py`                  | Draft candidates, approve/reject, claim validation   |
| `codeclone/memory/staleness.py`                   | Refresh-time and scope-time staleness                |
| `codeclone/config/memory*.py`                     | `[tool.codeclone.memory]` resolution                 |
| `codeclone/surfaces/cli/memory*.py`               | Human CLI + Rich rendering                           |
| `codeclone/surfaces/mcp/_session_memory_mixin.py` | MCP memory tools + finish hook                       |

Refs:

- `codeclone/memory/ingest/runner.py:run_memory_init`
- `codeclone/memory/retrieval/service.py:query_engineering_memory`
- `codeclone/surfaces/mcp/_session_memory_mixin.py`

---

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
        A[approve / reject / archive]
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
McpSync -->|ingest system records| Store
Never -.->|blocked|Store
```

| Action                                  | Who                                   | Resulting status                           |
|-----------------------------------------|---------------------------------------|--------------------------------------------|
| Init / refresh ingest                   | Human or CI (`codeclone memory init`) | `active` system records                    |
| Auto bootstrap / refresh from MCP run   | MCP when `mcp_sync_policy` allows     | `active` system records (same ingest path) |
| `refresh_from_run`                      | Agent MCP (explicit)                  | Force ingest from selected MCP run         |
| `record_candidate`                      | Agent MCP                             | `draft`                                    |
| `finish(propose_memory=true)` on accept | Agent MCP                             | `draft` proposals + staleness side effects |
| `approve`                               | Human CLI                             | `active` + `verified`/`supported`          |
| `reject`                                | Human CLI                             | `rejected`                                 |
| `archive`                               | Human CLI                             | `archived`                                 |
| Refresh detects drift                   | System on `init --refresh`            | `stale`                                    |
| Patch touches linked path               | System on accepted finish             | `stale`                                    |

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

Default retrieval excludes `stale` and `draft` unless
`include_stale=true` / `include_drafts=true`.

---

## Bootstrap: init, MCP sync, and refresh

The memory store can be created or refreshed through **CLI init**, **MCP auto-sync**
(default), or **explicit MCP refresh**. All paths call the same deterministic
ingest pipeline (`run_memory_init`).

### CLI init (human / CI)

```bash
codeclone memory init --root /abs/repo
codeclone memory init --root /abs/repo --refresh   # re-ingest + staleness pass
```

```mermaid
sequenceDiagram
    participant H as Human / CI
    participant CLI as codeclone memory init
    participant CC as CodeClone analysis
    participant DB as SQLite store
    H ->> CLI: init [--refresh]
    CLI ->> CC: load cached report or analyze
    CLI ->> CLI: build ingest batch
    Note over CLI: modules, contracts, docs,<br/>tests, risks, git hotspots
    CLI ->> DB: upsert records + evidence
    CLI ->> DB: rebuild FTS index
    opt --refresh
        CLI ->> DB: mark drifted records stale
    end
    CLI ->> H: status summary
```

### MCP sync (default agent path)

Policy key: `mcp_sync_policy` in `[tool.codeclone.memory]` (default
`bootstrap_if_missing`).

| Policy                 | Auto behavior on `get_relevant_memory`              | Explicit `refresh_from_run` |
|------------------------|-----------------------------------------------------|-----------------------------|
| `off`                  | No auto sync; DB must exist                         | Always runs ingest          |
| `bootstrap_if_missing` | Create store from latest MCP run when DB missing    | Always runs ingest          |
| `refresh_when_stale`   | Re-ingest when stored digest ≠ current run digest   | Always runs ingest          |

```mermaid
sequenceDiagram
    participant A as Agent
    participant M as MCP
    participant S as mcp_sync
    participant DB as SQLite store

    A->>M: analyze_repository
    M-->>A: run_id
    A->>M: start_controlled_change
    M-->>A: edit_allowed=true
    A->>M: get_relevant_memory(intent_id)
    M->>S: decide + execute (policy)
    alt missing DB + bootstrap_if_missing
        S->>DB: init ingest from run report
        S-->>M: memory_sync completed
    else digest changed + refresh_when_stale
        S->>DB: refresh ingest + staleness
        S-->>M: memory_sync completed
    else unchanged
        S-->>M: skip (no memory_sync field)
    end
    M->>DB: ranked scope query
    M-->>A: records + optional memory_sync
```

**Explicit refresh:** `manage_engineering_memory(action="refresh_from_run", run_id?)`
always ingests from the selected MCP run (defaults to latest). Use after
`analyze_repository` when you need fresh system facts without waiting for policy
triggers.

**Agent rule:** MCP sync ingests **system records only** — same as CLI init.
Human `approve` is still required for agent drafts. MCP never runs
approve/reject/archive.

When auto-sync does not run and the DB is missing, memory tools return a contract
error pointing to `refresh_from_run` or CLI init.

Ingest sources (non-exhaustive):

| Record type          | Typical ingest source                       |
|----------------------|---------------------------------------------|
| `module_role`        | Report file inventory                       |
| `contract_note`      | `codeclone/contracts/__init__.py`           |
| `document_link`      | Docs headings → repo paths                  |
| `test_anchor`        | Test file inventory                         |
| `risk_note`          | Complexity / security surfaces from metrics |
| `public_surface`     | MCP / CLI public API inventory              |
| `contradiction_note` | Cross-source conflicts during ingest        |

Git provenance (Phase 18.6): init attaches `git_commit` evidence when git is
available; optional git hotspot records use
`git_hotspot_period_days` / `git_hotspot_min_changes` from config.

Refs: `codeclone/memory/ingest/mcp_sync.py`, `codeclone/surfaces/mcp/_session_memory_mixin.py`.

---

## Configuration

Nested table in `pyproject.toml`:

```toml
[tool.codeclone.memory]
backend = "sqlite"
db_path = ".cache/codeclone/memory/engineering_memory.sqlite3"
max_records = 10000
max_candidates = 1000
git_hotspot_period_days = 90
git_hotspot_min_changes = 5
stale_retention_days = 180
draft_retention_days = 14
mcp_sync_policy = "bootstrap_if_missing"   # off | bootstrap_if_missing | refresh_when_stale
```

Environment override: `CODECLONE_MEMORY_DB_PATH`.

Refs:

- `codeclone/config/memory_specs.py`
- `codeclone/config/memory_defaults.py`

---

## CLI surface

All commands live under `codeclone memory` and accept `--root` (default `.`).

| Command                                                       | Purpose                                      |
|---------------------------------------------------------------|----------------------------------------------|
| `init [--refresh] [--dry-run]`                                | Create or refresh the memory store           |
| `status`                                                      | Schema version, counts, last ingest metadata |
| `for-path PATH [--limit N]`                                   | Records linked to a repo-relative path       |
| `search QUERY [--match any\|all] [--active-only] [--limit N]` | FTS keyword search                           |
| `stale [--limit N]`                                           | List stale records and reasons               |
| `vacuum [--dry-run]`                                          | Retention purge per config                   |
| `coverage --scope PATH [PATH...]`                             | Scope coverage metrics                       |
| `review-candidates [--limit N]`                               | List draft records awaiting human review     |
| `approve RECORD_ID [--verified-by NAME]`                      | Promote draft → active                       |
| `reject RECORD_ID [--reason TEXT]`                            | Reject draft                                 |
| `archive RECORD_ID [--reason TEXT]`                           | Archive record                               |

Human governance (`approve`, `reject`, `archive`) is **CLI-only** by design.

Refs:

- `codeclone/surfaces/cli/memory.py`
- `codeclone/surfaces/cli/memory_render.py`

---

## MCP surface

### Read tools

#### `get_relevant_memory`

Ranked, scope-aware context for the **declared edit scope**.

| Parameter                         | Purpose                                                       |
|-----------------------------------|---------------------------------------------------------------|
| `root`                            | Absolute repository root                                      |
| `scope`                           | Explicit repo-relative paths                                  |
| `intent_id`                       | Active intent from `start_controlled_change` (resolves scope) |
| `symbols`                         | Optional qualname keys for boost                              |
| `max_records`                     | Cap (default 20)                                              |
| `include_stale`, `include_drafts` | Default `false`                                               |

When neither `scope` nor `intent_id` is passed, returns a **project summary**
— useful for orientation, not pre-edit context.

When auto-sync runs, the response includes a `memory_sync` object (`status`,
`trigger`, `run_id`, `report_digest`, ingest stats). Omitted when sync was skipped
(`status: unchanged`).

#### `query_engineering_memory`

Mode router for inspection and search.

| `mode`       | Required inputs | Purpose                             |
|--------------|-----------------|-------------------------------------|
| `search`     | `query`         | FTS keyword search                  |
| `get`        | `record_id`     | Single record + subjects + evidence |
| `for_path`   | `path`          | Path-linked records                 |
| `for_symbol` | `symbol`        | Symbol-linked records               |
| `stale`      | —               | Stale inventory                     |
| `coverage`   | `scope`         | Coverage metrics for paths          |
| `status`     | —               | Store status (like CLI `status`)    |

**Filters** (`filters` object):

| Key           | Values                   | Notes                                 |
|---------------|--------------------------|---------------------------------------|
| `types`       | list of record types     | e.g. `["contract_note", "risk_note"]` |
| `statuses`    | list of statuses         | e.g. `["active"]`                     |
| `confidences` | list of confidences      | e.g. `["verified"]`                   |
| `match_mode`  | `any` (default) or `all` | **search mode only** — token matching |

CLI equivalent: `codeclone memory search QUERY --match any|all`.

### Write tools (draft layer)

#### `manage_engineering_memory`

| `action`               | Required params                                     | Effect                                                     |
|------------------------|-----------------------------------------------------|------------------------------------------------------------|
| `refresh_from_run`     | optional `run_id` (defaults to latest MCP run)      | Force ingest from MCP run report                           |
| `record_candidate`     | `record_type`, `statement`; optional `subject_path` | Creates **draft** record                                   |
| `validate_claims`      | `text`                                              | Memory-layer claim guard (warnings/errors)                 |
| `propose_from_receipt` | optional `text`, `intent_id`                        | Draft proposals from finish-like payload (atomic fallback) |

#### `finish_controlled_change(propose_memory=true)`

On **accepted** finish:

- proposes draft memory candidates from changed scope, claims, review text
- marks scope-linked **active** records stale
- returns `memory_candidates`, `memory_staleness`, `memory_coverage_delta`

This is the preferred post-edit memory update path when using the workflow
tools.

### Help topic

`help(topic="engineering_memory")` — compact agent playbook summary.

Refs:

- `codeclone/surfaces/mcp/server.py`
- `codeclone/surfaces/mcp/messages/help_topics.py`
- `codeclone/surfaces/mcp/_session_workflow_mixin.py` (finish hook)

---

## Agent playbook

### When to read memory

```mermaid
flowchart TD
    A[analyze_repository] --> B[start_controlled_change]
    B --> C{edit_allowed?}
    C -->|no| Z[Stop — queue / blocked / needs_analysis]
C -->|yes|D[get_relevant_memory]
D --> E{contradiction_note\nor stale warnings?}
E -->|yes|F[Surface to user before edit]
E -->|no|G[Edit in declared scope]
G --> H[analyze if profile requires after_run]
H --> I[finish_controlled_change]
I --> J{propose_memory?}
J -->|true + accepted|K[Review memory_candidates\nhuman approve later]
J -->|false|L[Done]

style D fill: #eff6ff
style G fill: #fef9c3
```

| Moment                           | Tool                                                                     | Why                                           |
|----------------------------------|--------------------------------------------------------------------------|-----------------------------------------------|
| After `start`, before first edit | `get_relevant_memory(scope=… \| intent_id=…)`                            | Ranked context for declared scope             |
| Need one path deep-dive          | `query_engineering_memory(mode=for_path, path=…)`                        | Targeted lookup                               |
| Need keyword across store        | `query_engineering_memory(mode=search, query=…, filters={match_mode:…})` | FTS discovery                                 |
| Before writing claims in finish  | `manage_engineering_memory(action=validate_claims, text=…)`              | Catch overclaims vs memory                    |
| After accepted patch (optional)  | `finish(..., propose_memory=true)`                                       | Draft candidates + staleness + coverage delta |

### When to write memory

| Situation                        | Action                                   | Notes                               |
|----------------------------------|------------------------------------------|-------------------------------------|
| Stable observation during edit   | `record_candidate`                       | Draft only; cite scope in statement |
| Patch accepted, workflow finish  | `propose_memory=true`                    | Preferred batch proposal            |
| Atomic fallback (no finish hook) | `propose_from_receipt`                   | Same receipt shape as finish        |
| System facts changed in repo     | `refresh_from_run` or ask human for `memory init --refresh` | Explicit MCP refresh always available |
| Promote draft to trusted fact    | **Not agent** — human `memory approve`   | Required for active/verified        |

### When **not** to use memory

- To justify touching `do_not_touch` paths
- To expand scope beyond declared intent
- To override CodeClone structural findings
- As a substitute for `analyze_repository` or `get_blast_radius`
- To treat `draft` / `inferred` / `stale` records as established facts

---

## Staleness

```mermaid
flowchart TD
    subgraph Refresh["init --refresh"]
        R1[missing_from_refresh]
        R2[evidence_digest_mismatch]
        R3[linked_path_missing]
        R4[refresh_content_contradiction]
        R5[report_digest_shift]
    end

    subgraph Scope["accepted finish"]
        S1[scope_files_changed]
    end

    Refresh --> ST[(status = stale)]
    Scope --> ST
    ST --> RE[Excluded from default retrieval]
    RE --> RA[Reactivate on refresh if content matches]
```

Stale records remain in the database for audit but are **excluded** from
`get_relevant_memory` and default search unless explicitly included.

---

## Search semantics (schema 1.1)

FTS5 index (`memory_fts`) indexes record statements and metadata.

| `match_mode`    | Behavior                                      |
|-----------------|-----------------------------------------------|
| `any` (default) | Match records containing **any** query token  |
| `all`           | Match records containing **all** query tokens |

Document links display as normalized headings, e.g.
`AGENTS.md · §16 · Change routing → AGENTS.md`.

Refs:

- `codeclone/memory/search_index.py`
- `codeclone/memory/display.py`

---

## Integration with change control

Memory complements — does not replace — the Structural Change Controller
([24-structural-change-controller.md](24-structural-change-controller.md)):

```mermaid
graph LR
    CC[Change Controller] -->|scope, blast, verify| Edit[Scoped edit]
    EM[Engineering Memory] -->|context, drafts| Edit
    Edit --> CC
    CC -->|propose_memory| EM
    style CC stroke: #6366f1
    style EM stroke: #059669
```

| Controller fact                | Memory fact                         |
|--------------------------------|-------------------------------------|
| `do_not_touch` — hard boundary | `risk_note` — informational hotspot |
| Patch verify `accepted`        | `change_rationale` draft proposal   |
| Blast radius dependents        | `module_role` inventory link        |

---

## Invariants (MUST)

- Memory store path defaults under `.cache/codeclone/memory/` — not baseline or analysis cache.
- Init ingest is deterministic given identical report + git inputs.
- MCP memory tools are read-only except draft writes through governance actions.
- Human approve/reject/archive never exposed on MCP.
- Subject rows deduplicated in retrieval payloads (one row per logical subject key).
- FTS rebuilt after init/refresh ingest completes.
- Schema migration is forward-only through `schema_migrate.py`.

---

## Failure modes

| Condition                | Behavior                                                                       |
|--------------------------|--------------------------------------------------------------------------------|
| DB missing, policy `off` | MCP error: run `refresh_from_run` or CLI init                                  |
| DB missing, default policy | Auto bootstrap on `get_relevant_memory` when MCP run exists                  |
| No MCP run for sync      | Auto sync skipped; DB missing → contract error                                 |
| At `max_candidates`      | `record_candidate` raises capacity error       |
| At `max_records`         | Init upsert skips or rejects per store policy  |
| No cached report on init | Init runs analysis or fails with clear message |
| Git unavailable          | Init proceeds; git evidence/hotspots skipped   |

---

## Locked by tests

- `tests/test_memory_mcp_sync.py`
- `tests/test_memory_store.py`
- `tests/test_memory_search.py`
- `tests/test_memory_retrieval.py`
- `tests/test_memory_staleness.py`
- `tests/test_memory_governance.py`
- `tests/test_memory_cli.py`
- `tests/test_mcp_service.py` (memory tool wiring)
- `tests/test_mcp_server.py` (tool registration)

---

## Related docs

- [MCP Interface](20-mcp-interface.md) — tool catalog
- [Structural Change Controller](24-structural-change-controller.md) — intent workflow
- [Claim Guard](28-claim-guard.md) — finish claims validation
- [CLI](09-cli.md) — `codeclone memory` commands
- [MCP for AI Agents](../mcp.md) — agent-oriented narrative
