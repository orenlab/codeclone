### Session-local tools

| Tool                     | Key parameters                 | Purpose                                                                                               |
|--------------------------|--------------------------------|-------------------------------------------------------------------------------------------------------|
| `mark_finding_reviewed`  | `finding_id`, `run_id`, `note` | Session-local review marker (in-memory)                                                               |
| `list_reviewed_findings` | `run_id`                       | List reviewed markers for a run                                                                       |
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

`get_relevant_memory` responses may include passive `context_governance`
metadata with estimated context units for the serialized payload. In
`mode="observe"` this is measurement only: `records`, `trajectories`,
`experiences`, coverage, and retrieval-policy fields keep their documented lane
semantics and are not omitted by response governance.
