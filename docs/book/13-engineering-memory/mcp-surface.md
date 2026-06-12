## MCP surface

### Read tools

#### `get_relevant_memory`

Ranked, scope-aware context for the **declared edit scope**.

| Parameter                         | Purpose                                                                                                         |
|-----------------------------------|-----------------------------------------------------------------------------------------------------------------|
| `root`                            | **Required.** Absolute repository root (same as `analyze_repository`)                                           |
| `scope`                           | Explicit repo-relative paths                                                                                    |
| `intent_id`                       | Active intent from `start_controlled_change` (resolves scope)                                                   |
| `symbols`                         | Optional qualname keys for boost                                                                                |
| `max_records`                     | Cap (default 20)                                                                                                |
| `include_stale`, `include_drafts` | `include_stale` defaults false; drafts are automatic for scoped retrieval / path / symbol and opt-in for search |
| `detail_level`                    | `compact` (default) or `full` — compact returns statement previews without payload                              |

Unscoped `get_relevant_memory` is **rejected**. Pass `scope`, `intent_id`, or
`symbols`. For project-wide orientation use
`query_engineering_memory(mode=status|search)` — not root scope (`"."`, `""`).

Project root is never a valid memory scope for `scope`, `path`, or `coverage`.

`intent_id` or `scope` without `root` fails MCP argument validation (Pydantic).
Always pass the same absolute `root` used for `analyze_repository` and
`start_controlled_change`.

When auto-sync runs, the response includes a `memory_sync` object (`status`,
`trigger`, `run_id`, `report_digest`, ingest stats). Omitted when sync was skipped
(`status: unchanged`).

#### `query_engineering_memory`

Mode router for inspection and search.

| `mode`       | Required inputs                       | Purpose                                   |
|--------------|---------------------------------------|-------------------------------------------|
| `search`     | `query`; optional `semantic=true`     | FTS keyword search; optional vector blend |
| `get`        | `record_id`                           | Single record + subjects + evidence       |
| `for_path`   | `path`                                | Path-linked records                       |
| `for_symbol` | `symbol`                              | Symbol-linked records                     |
| `stale`      | —                                     | Stale inventory                           |
| `coverage`   | `scope` (non-empty, not project root) | Coverage metrics for paths                |
| `status`     | —                                     | Store status (like CLI `status`)          |
| `drafts`     | optional `limit`                      | Draft inbox (compact by default)          |
| `trajectory_status` | —                              | Trajectory projection run metadata        |
| `trajectory_search` | `query`; optional `filters.include_routine` | Search stored trajectories |
| `trajectory_get`    | `record_id` (trajectory id)    | One trajectory + steps (always full)      |
| `trajectory_anomalies` | optional `filters.include_routine` | Detected trajectory contract anomalies |
| `trajectory_agents`    | optional `filters.include_routine` | Aggregate quality/outcomes by exact agent label |
| `trajectory_dashboard` | optional `filters.include_routine` | Combined status, agent, and anomaly view |

List modes (`search`, `stale`, `drafts`, scoped `get_relevant_memory`) default
to **compact** payloads: statement preview, `statement_length`, no `payload`.
Use `mode=get` or `detail_level=full` for complete statements and payload.
`trajectory_get` is also always full regardless of requested detail level.

Scoped retrieval keeps four typed lanes:

| Lane             | Meaning                                      | `compact`                                                     | `full`                                      |
|------------------|----------------------------------------------|---------------------------------------------------------------|---------------------------------------------|
| `records[]`      | Durable asserted/project memory              | Preview; relevance-first bounded `subjects`; count/truncation | Full statement, subjects, record payload    |
| `experiences[]`  | Advisory patterns distilled from trajectories | Preview; agent-family count, multi-agent flag, dominant facet | Full agent facets and trajectory evidence ids |
| `trajectories[]` | Prior workflow examples/evidence             | Bounded preview; no steps or `quality_contract`               | Full contract/subjects; use `trajectory_get` for steps |
| `coverage`       | Availability of record/trajectory/experience context | Same factual coverage metadata                                | Same factual coverage metadata              |

`subject_count` and `subjects_truncated=true` mean more linked subjects exist;
they do not downgrade or discard the record. Each compact trajectory retains
its own `patch_trail_summary`. The duplicate top-level `patch_trail_summary` is
full-only.

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

| `action`                 | Required params                                     | Effect                                                     |
|--------------------------|-----------------------------------------------------|------------------------------------------------------------|
| `refresh_from_run`       | optional `run_id` (defaults to latest MCP run)      | Force ingest from MCP run report                           |
| `rebuild_semantic_index` | (none)                                              | Rebuild LanceDB sidecar when `memory.semantic.enabled`     |
| `rebuild_trajectories`   | (none)                                              | Rebuild trajectory projections from audit event core       |
| `enqueue_projection_rebuild` | (none)                                              | Queue trajectory + semantic + Experience projection job    |
| `projection_rebuild_status` | (none)                                           | Latest projection job status                               |
| `run_projection_jobs_once` | (none)                                           | Run one queued projection job inline                       |
| `record_candidate`       | `record_type`, `statement`, **`subject_path`**      | Creates **draft** record                                   |
| `promote_experience`     | `experience_id`                                     | Convert advisory Experience into human-reviewable draft    |
| `validate_claims`        | `text`                                              | Memory-layer claim guard (warnings/errors)                 |
| `propose_from_receipt`   | optional `text`, `intent_id`                        | Draft proposals from finish-like payload (atomic fallback) |

IDE channel only (VS Code launches MCP with `--ide-governance-channel`):

| `action`                  | Purpose                                                 |
|---------------------------|---------------------------------------------------------|
| `register_ide_governance` | Bind session HMAC key + client attestation              |
| `prepare_governance`      | Issue ticket + nonce + `statement_digest` (protocol v2) |
| `commit_governance`       | Human confirm with HMAC proof → approve/reject/archive  |

Agent calls to `approve`, `reject`, or `archive` return `governance_mode_unavailable`
with `next_step` pointing to the VS Code Memory view (never CLI instructions).

#### `finish_controlled_change(propose_memory=true)`

On **accepted** or **accepted_with_external_changes** finish:

- proposes draft memory candidates from changed scope, claims, review text
- marks scope-linked **active** records stale
- returns `memory_candidates`, `memory_staleness`, `memory_coverage_delta`
- when `memory.projection_rebuild_policy` is not `off` and the environment is
  not CI, may enqueue a projection rebuild job (`projection_rebuild` in the
  finish payload — trajectory, semantic, and Experience projections)

This is the preferred post-edit memory update path when using the workflow
tools.

### Help topic

`help(topic="engineering_memory")` — compact agent playbook summary.

Trajectory analytics and Experience semantics are specified in
[Trajectory quality and passport](trajectory-quality-and-passport.md) and
[Experience Layer](experience-layer.md).

Refs:

- `codeclone/surfaces/mcp/server.py`
- `codeclone/surfaces/mcp/messages/help_topics.py`
- `codeclone/surfaces/mcp/_session_workflow_mixin.py` (finish hook)

---
