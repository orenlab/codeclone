# 20. MCP Interface

## Purpose

Define the current public MCP surface in `2.0.0b3`.

This interface is **optional** and is installed via the `mcp` extra. It does
not replace the CLI or the canonical JSON report contract. Instead, it exposes
the existing deterministic analysis pipeline as a **read-only MCP server** for
AI agents and MCP-capable clients.

## Public surface

- Package extra: `codeclone[mcp]`
- MCP launcher: `codeclone-mcp`
- MCP server: `codeclone/mcp_server.py`
- MCP service adapter: `codeclone/mcp_service.py`

## Data model

Current server characteristics:

- optional dependency; base `codeclone` install does not require `mcp`
- transports:
    - `stdio`
    - `streamable-http`
- run storage:
    - in-memory only
    - bounded history (`--history-limit`, default `16`)
    - latest-run pointer for `codeclone://latest/...` resources
- run identity:
    - `run_id` is derived from the canonical report integrity digest
- analysis modes:
    - `full`
    - `clones_only`
- cache policies:
    - `reuse`
    - `refresh`
    - `off`
- summary payload:
    - `run_id`, `root`, `analysis_mode`
    - `baseline`, `metrics_baseline`, `cache`
    - `inventory`, `findings_summary`, `health`
    - `baseline_diff`, `metrics_diff`
    - `warnings`, `failures`

The MCP layer does not introduce a separate analysis engine. It calls the
current CodeClone pipeline and reuses the canonical report document already
produced by the report contract.

## Tools

Current tool set:

| Tool                 | Purpose                                                                                                          |
|----------------------|------------------------------------------------------------------------------------------------------------------|
| `analyze_repository` | Run deterministic CodeClone analysis and register the result as the latest MCP run                               |
| `get_run_summary`    | Return the stored summary for the latest or specified run                                                        |
| `evaluate_gates`     | Evaluate CI/gating conditions against an existing run without exiting the process                                |
| `get_report_section` | Return a canonical report section (`meta`, `inventory`, `findings`, `metrics`, `derived`, `integrity`, or `all`) |
| `list_findings`      | Return deterministically ordered finding groups with filters and pagination                                      |
| `get_finding`        | Return one canonical finding group by id                                                                         |
| `list_hotspots`      | Return one derived hotlist (`most_actionable`, `highest_spread`, `production_hotspots`, `test_fixture_hotspots`) |

All current tools are registered as read-only MCP tools.

## Resources

Current resources:

- `codeclone://latest/summary`
- `codeclone://latest/report.json`
- `codeclone://runs/{run_id}/summary`
- `codeclone://runs/{run_id}/report.json`
- `codeclone://runs/{run_id}/findings/{finding_id}`

Resources are convenience views over already registered runs. They do not
trigger fresh analysis by themselves.

## Contracts

- MCP is **read-only**:
    - no source-file mutation
    - no baseline update
    - no metrics-baseline update
- MCP must reuse current:
    - pipeline stages
    - baseline trust semantics
    - cache semantics
    - canonical report contract
- `get_run_summary` is a deterministic convenience projection derived from the
  canonical report (`meta`, `inventory`, `findings.summary`,
  `metrics.summary.health`) plus baseline-diff/gate context.
- Canonical JSON remains the source of truth for report semantics.
- `list_findings` and `list_hotspots` are deterministic projections over the
  canonical report, not a separate analysis branch.
- `analysis_mode="clones_only"` must mirror the same metric/dependency
  skip-semantics as the regular pipeline.
- Missing optional MCP dependency is handled explicitly by the launcher with a
  user-facing install hint and exit code `2`.

## Invariants (MUST)

- Tool names are stable public surface.
- Resource URI shapes are stable public surface.
- Read-only tool annotations remain accurate.
- `analyze_repository` always registers exactly one latest run.
- `get_run_summary` with no `run_id` resolves to the latest stored run.
- `get_report_section(section="all")` returns the full canonical report document.
- `run_id` must equal the canonical report digest for that run.

## Failure modes

| Condition                                  | Behavior                                          |
|--------------------------------------------|---------------------------------------------------|
| `mcp` extra not installed                  | `codeclone-mcp` prints install hint and exits `2` |
| Invalid root path / invalid numeric config | service raises contract error                     |
| Requested run missing                      | service raises run-not-found error                |
| Requested finding missing                  | service raises finding-not-found error            |
| Unsupported report section/resource suffix | service raises contract error                     |

## Determinism / canonicalization

- MCP run identity is derived from canonical report integrity digest.
- Finding order is inherited from canonical report ordering.
- Hotlists are derived from canonical report data and deterministic derived ids.
- No MCP-only heuristics may change analysis or gating semantics.

## Locked by tests

- `tests/test_mcp_service.py::test_mcp_service_analyze_repository_registers_latest_run`
- `tests/test_mcp_service.py::test_mcp_service_lists_findings_and_hotspots`
- `tests/test_mcp_service.py::test_mcp_service_evaluate_gates_on_existing_run`
- `tests/test_mcp_service.py::test_mcp_service_resources_expose_latest_summary_and_report`
- `tests/test_mcp_server.py::test_mcp_server_exposes_expected_read_only_tools`
- `tests/test_mcp_server.py::test_mcp_server_tool_roundtrip_and_resources`
- `tests/test_mcp_server.py::test_mcp_server_main_reports_missing_optional_dependency`

## Non-guarantees

- There is currently no standalone `mcp_api_version` constant.
- In-memory run history does not survive process restart.
- Client-specific UI/approval behavior is not part of the CodeClone contract.

## See also

- [09-cli.md](09-cli.md)
- [08-report.md](08-report.md)
- [14-compatibility-and-versioning.md](14-compatibility-and-versioning.md)
- [../mcp.md](../mcp.md)
