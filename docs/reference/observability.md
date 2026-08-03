---
title: "Platform observability"
audience: public
doc_type: reference
status: published
source_commit: "60eac9c367d74deeba1478521461addfedd8e681"
---

# Platform observability

Platform observability is a **development-only diagnostic** over CodeClone's
*own* runtime telemetry. It exists to help maintainers build and profile
CodeClone itself.

!!! warning "Not a repository quality signal"
    Observability measures CodeClone's runtime, not your code. High database
    query counts, large MCP payloads, or a hot semantic reindex say nothing
    about the quality or safety of the repository being analyzed. It never
    affects reports, gates, baselines, memory facts, or edit authorization.

## Disabled by default

Observability is off unless you explicitly enable it through environment
variables. When disabled (or when no telemetry store exists), the diagnostic
returns an inert `status=disabled` / `status=no_store` envelope rather than an
error.

| Environment variable | Purpose |
|----------------------|---------|
| `CODECLONE_OBSERVABILITY_ENABLED` | Master switch — turns telemetry capture on |
| `CODECLONE_OBSERVABILITY_PERSIST` | Persist captured spans to the local store |
| `CODECLONE_OBSERVABILITY_PROFILE` | Per-phase profiling **and all memory/CPU sampling** — see below |
| `CODECLONE_OBSERVABILITY_CAPTURE_PAYLOAD_SIZES` | Record payload sizes (numeric only) |
| `CODECLONE_OBSERVABILITY_FORCE` | Lift the CI gate below; does not enable capture on its own |
| `CODECLONE_OBSERVABILITY_CORRELATION_ID` / `CODECLONE_OBSERVABILITY_PARENT_OPERATION_ID` | Correlate spans across a chain |

!!! important "Memory columns need `CODECLONE_OBSERVABILITY_PROFILE`"
    `CODECLONE_OBSERVABILITY_ENABLED=1` on its own records spans with **NULL**
    `rss_mb`, `peak_rss_mb` and CPU columns. Memory and CPU are sampled only
    when profiling is on, so any memory question needs both variables:

    ```bash
    export CODECLONE_OBSERVABILITY_ENABLED=1
    export CODECLONE_OBSERVABILITY_PROFILE=1
    ```

    Profiling requires the `codeclone[perf]` extra (psutil). It fails loudly
    with `ObservabilityConfigError` when psutil is missing rather than silently
    dropping the columns.

    Cross-check in-process numbers against the OS. `peak_rss_mb` samples at
    span boundaries and reads a few percent below `/usr/bin/time -l`
    (`maximum resident set size`).

!!! note "Capture is off by default in CI"
    In a detected CI environment observability stays disabled unless
    `CODECLONE_OBSERVABILITY_ENABLED` is set to an explicit true value. An
    explicit enable is sufficient — `CODECLONE_OBSERVABILITY_FORCE` only lifts
    the CI gate and never enables capture by itself.

## How to read it

The maintainer-facing surface is the MCP tool `query_platform_observability`, a
read-only sectioned slicer. It emits **numeric metrics only** — never raw SQL or
payloads. Start at the `summary` section and follow the recommended next
sections:

`summary` · `slow_operations` · `memory_pipeline_cost` · `db_cost` ·
`agent_context` · `mcp_tool_matrix` · `correlated_chains` · `costly_noops` ·
`pipeline` · `analysis_phase_cost`

`detail_level` accepts `compact`, `normal`, or `full` (aggregate sections
downgrade `full` to `normal`); `limit` clamps to `[1, 100]`. The
branded HTML cockpit remains the human-facing everything-view.

For the maintainer-only skill, see `codeclone-platform-observability`; in an MCP
client, `help(topic="observability")` gives the compact contract.
