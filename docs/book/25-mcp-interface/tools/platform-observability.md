# Platform Observability Tool

<!-- doc-scope: contract -->

`query_platform_observability` projects bounded diagnostics from CodeClone's
local observer store. It is intended **only** for CodeClone maintainers
developing the product — **not** for users evaluating their analyzed
repository.

!!! warning "Prerequisites"
    Observation is **off by default**. Set `CODECLONE_OBSERVABILITY_ENABLED=1`
    on the CLI/MCP/worker process **before** reproduction. Without enablement
    the tool returns `status=disabled` or `status=no_store` and provides no
    repository-quality signal.

    See [Platform Observability](../../26-platform-observability.md) for storage,
    privacy, configuration, and trust boundaries.

## Parameters

| Parameter      | Contract                                                                 |
|----------------|--------------------------------------------------------------------------|
| `root`         | Absolute repository root.                                                |
| `section`      | One supported diagnostics section.                                       |
| `detail_level` | `compact`, `normal`, or `full`; `full` currently downgrades to `normal`. |
| `limit`        | Row cap, clamped to `1..50`.                                             |
| `window`       | `latest` or a correlation ID.                                            |
| `operation_id` | Reserved; reported in `ignored_parameters`.                              |
| `span_id`      | Reserved; reported in `ignored_parameters`.                              |

Supported sections:

- `summary`
- `slow_operations`
- `memory_pipeline_cost`
- `db_cost`
- `agent_context`
- `mcp_tool_matrix`
- `correlated_chains`
- `costly_noops`
- `pipeline`
- `analysis_phase_cost`

Each call returns one section only. Compact detail is bounded to five rows;
normal detail is bounded by `limit`.

`analysis_phase_cost` reports summed worker elapsed time inside
`pipeline.process`, grouped by analysis micro-phase. The top-level scalar
`phase_worker_elapsed_total_ms` may exceed `pipeline_process_wall_ms` when
analysis ran in a process pool. Treat the section as a CodeClone performance
diagnostic only; it does not indicate repository quality.

## Inert states

When observability is disabled, the tool returns a disabled status. When no
local store exists, it returns a no-store status. Neither state changes
analysis behavior.

An invalid section returns the available section names. Reserved parameters
are echoed as ignored instead of changing the projection.

## Interpretation boundary

The envelope states that:

- the audience is CodeClone development;
- the data is not user-facing repository quality evidence;
- it does not affect reports, gates, baselines, memory facts, or edit
  authorization;
- reported heuristics are diagnostic hints, not findings.

This anti-inference boundary is part of the tool contract. See
[Determinism and tests](../determinism-and-tests.md) and the
[diagnostics guide](../../../guide/observability/diagnostics.md).
