### Session-local tools

| Tool                     | Key parameters                 | Purpose                                                                                               |
|--------------------------|--------------------------------|-------------------------------------------------------------------------------------------------------|
| `mark_finding_reviewed`  | `finding_id`, `run_id`, `note` | Session-local review marker (in-memory)                                                               |
| `list_reviewed_findings` | `run_id`                       | List reviewed markers for a run                                                                       |
| `get_implementation_context_page` | `root`, `context_projection_digest`, `facet`, `offset`, `page_size` | Exact page from a `get_implementation_context` session-local projection artifact. Returns `not_found` after the projection leaves MCP run history; never recomputes fresh context as exact evidence |
| `clear_session_runs`     | —                              | Reset in-memory runs, session review markers, and workspace intent registry state for the MCP process |

### Platform observability

| Tool                           | Key parameters                                       | Purpose                                                        |
|--------------------------------|------------------------------------------------------|----------------------------------------------------------------|
| `query_platform_observability` | `root`, `section`, `window`, `detail_level`, `limit` | Bounded, read-only slices of CodeClone's own runtime telemetry |

This tool is **development-only**. It reports numeric operation/span,
database-cost, payload, agent-context, and pipeline diagnostics for CodeClone
itself. It never contributes repository findings, gates, baselines, memory
facts, or edit authorization, and it does not expose raw SQL or payload bodies.
See the dedicated
[Platform Observability tool contract](platform-observability.md).

Compact `get_relevant_memory` responses include `context_governance` metadata
with `mode="partial_enforce"` and
`evidence_policy="response_budget_with_exact_continuation"`. `records`,
`trajectories`, `experiences`, coverage, and retrieval-policy fields keep their
documented lane semantics; if a lane is omitted or reduced by the response
budget, `context_governance.omitted` names the lane and points to its exact
continuation cursor. Full-detail memory retrieval and continuation pages stay in
`mode="observe"`.

When a memory lane has more deterministic items than the default response shows,
`get_relevant_memory` includes `continuation.lanes.<lane>.page`. Pass that
digest-bound cursor to `get_memory_projection_page` to enumerate the omitted
tail exactly. The cursor binds to the normalized request, lane ordering version,
and lane identity digest; if the underlying memory projection changed, the page
returns `status="snapshot_mismatch"` instead of continuing against fresh data.

Known identities still use object lookups:

- memory records: `query_engineering_memory(mode="get", record_id=...)`;
- trajectories: `query_engineering_memory(mode="trajectory_get", record_id=...)`;
- Experiences: `query_engineering_memory(mode="experience_get", record_id=...)`.

`get_implementation_context` responses may include
`analysis.context_page_retrieval`. Use
`analysis.context_projection_digest` plus a facet key such as `public_surface`,
`callers`, `memory`, `trajectories`, or `definition_sites` with
`get_implementation_context_page` to retrieve the exact saved facet lane for
the current MCP session. This is not a fresh analysis and it is not durable
beyond MCP run-history retention.
