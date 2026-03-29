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
    - bounded history (`--history-limit`, default `4`, maximum `10`)
    - latest-run pointer for `codeclone://latest/...` resources
- run identity:
    - `run_id` is derived from the canonical report integrity digest
- analysis modes:
    - `full`
    - `clones_only`
- process-count policy:
    - `processes` is an optional override
    - when omitted, MCP defers to the core CodeClone runtime
- cache policies:
    - `reuse`
    - `off`
      `refresh` is rejected in MCP because the server is read-only.
- summary payload:
    - `run_id`, `root`, `analysis_mode`
    - `baseline`, `metrics_baseline`, `cache`
    - `inventory`, `findings_summary`, `health`
    - `get_run_summary` and summary resources expose slim inventory
      `file_registry` as `{ encoding, count }`
    - `analyze_repository` keeps the full `inventory.file_registry.items`
    - `analyze_changed_paths` also returns slim inventory `file_registry`
    - `baseline_diff`, `metrics_diff`
    - optional `changed_paths` (`list[str]`, repo-relative),
      `changed_findings`, `health_delta`, `verdict`
    - `warnings`, `failures`
- finding-list payloads:
    - `list_findings`, `list_hotspots`, and `check_*` include envelope-level
      `base_uri` once per response
    - `detail_level="summary"` keeps only compact location tuples
      (`file` + `line`) and omits `priority_factors`
    - `detail_level="normal"` keeps `symbol` in locations but omits `uri` and
      `priority_factors`
    - `detail_level="full"` keeps `priority_factors`, location `symbol`, and
      per-location `uri` for compatibility-oriented consumers

The MCP layer does not introduce a separate analysis engine. It calls the
current CodeClone pipeline and reuses the canonical report document already
produced by the report contract.

## Tools

Current tool set:

| Tool                     | Key parameters                                                                                                                                         | Purpose / notes                                                                                                                                                                |
|--------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `analyze_repository`     | `root`, `analysis_mode`, `changed_paths`, `git_diff_ref`, inline thresholds, cache/baseline paths                                                      | Run deterministic CodeClone analysis and register the result as the latest MCP run                                                                                             |
| `analyze_changed_paths`  | `root`, `changed_paths` or `git_diff_ref`, `analysis_mode`, inline thresholds                                                                          | Diff-aware fast path: analyze a repo and attach a changed-files projection to the run; summary inventory is slimmed to `{count}`                                               |
| `get_run_summary`        | `run_id`                                                                                                                                               | Return the stored summary for the latest or specified run, with slim inventory counts instead of the full file registry                                                        |
| `compare_runs`           | `run_id_before`, `run_id_after`, `focus`                                                                                                               | Compare two registered runs by finding ids and health delta                                                                                                                    |
| `evaluate_gates`         | `run_id`, gate thresholds/booleans                                                                                                                     | Evaluate CI/gating conditions against an existing run without exiting the process                                                                                              |
| `get_report_section`     | `run_id`, `section`                                                                                                                                    | Return a canonical report section. `metrics` is summary-only; `metrics_detail` exposes the full metrics payload; other sections stay canonical                                 |
| `list_findings`          | `family`, `category`, `severity`, `source_kind`, `novelty`, `sort_by`, `detail_level`, `changed_paths`, `git_diff_ref`, `exclude_reviewed`, pagination | Return deterministically ordered finding groups with filtering and pagination; list responses include `base_uri` and compact summary/normal projections                        |
| `get_finding`            | `finding_id`, `run_id`                                                                                                                                 | Return one canonical finding group by id with locations, priority, and remediation payload when available; this endpoint remains full-detail                                   |
| `get_remediation`        | `finding_id`, `run_id`, `detail_level`                                                                                                                 | Return just the remediation/explainability packet for one finding                                                                                                              |
| `list_hotspots`          | `kind`, `run_id`, `detail_level`, `changed_paths`, `git_diff_ref`, `exclude_reviewed`, `limit`, `max_results`                                          | Return one derived hotlist (`most_actionable`, `highest_spread`, `highest_priority`, `production_hotspots`, `test_fixture_hotspots`) with compact summary cards and `base_uri` |
| `check_clones`           | `run_id`, `root`, `path`, `clone_type`, `source_kind`, `max_results`, `detail_level`                                                                   | Return clone findings from a compatible stored run; `health.dimensions` includes only `clones`                                                                                 |
| `check_complexity`       | `run_id`, `root`, `path`, `min_complexity`, `max_results`, `detail_level`                                                                              | Return complexity hotspots from a compatible stored run; `health.dimensions` includes only `complexity`                                                                        |
| `check_coupling`         | `run_id`, `root`, `path`, `max_results`, `detail_level`                                                                                                | Return coupling hotspots from a compatible stored run; `health.dimensions` includes only `coupling`                                                                            |
| `check_cohesion`         | `run_id`, `root`, `path`, `max_results`, `detail_level`                                                                                                | Return cohesion hotspots from a compatible stored run; `health.dimensions` includes only `cohesion`                                                                            |
| `check_dead_code`        | `run_id`, `root`, `path`, `min_severity`, `max_results`, `detail_level`                                                                                | Return dead-code findings from a compatible stored run; `health.dimensions` includes only `dead_code`                                                                          |
| `generate_pr_summary`    | `run_id`, `changed_paths`, `git_diff_ref`, `format`                                                                                                    | Build a PR-friendly changed-files summary in markdown or JSON                                                                                                                  |
| `mark_finding_reviewed`  | `finding_id`, `run_id`, `note`                                                                                                                         | Mark a finding as reviewed in the in-memory MCP session                                                                                                                        |
| `list_reviewed_findings` | `run_id`                                                                                                                                               | Return the current reviewed findings for the selected run                                                                                                                      |
| `clear_session_runs`     | none                                                                                                                                                   | Clear all stored in-memory runs plus ephemeral review/gate/session caches for the current server process                                                                       |

All analysis/report tools are read-only with respect to repo state. The only
mutable MCP tools are `mark_finding_reviewed` and `clear_session_runs`, and
their effects are session-local and in-memory only. `analyze_repository`,
`analyze_changed_paths`, and `evaluate_gates` are
sessionful and may populate or reuse in-memory run state. The granular
`check_*` tools are read-only over stored runs: use `analyze_repository` or
`analyze_changed_paths` first, then query the latest run or pass a specific
`run_id`.

## Resources

Current resources:

| Resource                                          | Payload                                               | Availability                                          |
|---------------------------------------------------|-------------------------------------------------------|-------------------------------------------------------|
| `codeclone://latest/summary`                      | latest run summary projection                         | always after at least one run                         |
| `codeclone://latest/report.json`                  | latest canonical report document                      | always after at least one run                         |
| `codeclone://latest/health`                       | latest health score + dimensions                      | always after at least one run                         |
| `codeclone://latest/gates`                        | latest gate evaluation result                         | only after `evaluate_gates` in current server process |
| `codeclone://latest/changed`                      | latest changed-files projection                       | only for a diff-aware latest run                      |
| `codeclone://schema`                              | schema-style descriptor for canonical report sections | always available                                      |
| `codeclone://runs/{run_id}/summary`               | run-specific summary projection                       | for any stored run                                    |
| `codeclone://runs/{run_id}/report.json`           | run-specific canonical report                         | for any stored run                                    |
| `codeclone://runs/{run_id}/findings/{finding_id}` | run-specific canonical finding group                  | for an existing finding in a stored run               |

Resources are convenience views over already registered runs. They do not
trigger fresh analysis by themselves.

## Contracts

- MCP is **read-only**:
    - no source-file mutation
    - no baseline update
    - no metrics-baseline update
    - no cache refresh writes
- Session review markers are **ephemeral only**:
    - stored in memory per server process
    - never written to baseline, cache, or report artifacts
- `streamable-http` defaults to loopback binding.
  Non-loopback hosts require explicit `--allow-remote` because the server has
  no built-in authentication.
- MCP must reuse current:
    - pipeline stages
    - baseline trust semantics
    - cache semantics
    - canonical report contract
- `get_run_summary` is a deterministic convenience projection derived from the
  canonical report (`meta`, `inventory`, `findings.summary`,
  `metrics.summary.health`) plus baseline-diff/gate/changed-files context.
- Canonical JSON remains the source of truth for report semantics.
- `list_findings` and `list_hotspots` are deterministic projections over the
  canonical report, not a separate analysis branch.
- `get_remediation` is a deterministic MCP projection over existing
  suggestions/explainability data, not a second remediation engine.
- `analysis_mode="clones_only"` must mirror the same metric/dependency
  skip-semantics as the regular pipeline.
- Missing optional MCP dependency is handled explicitly by the launcher with a
  user-facing install hint and exit code `2`.

## Invariants (MUST)

- Tool names are stable public surface.
- Resource URI shapes are stable public surface.
- Read-only vs session-local tool annotations remain accurate.
- `analyze_repository` always registers exactly one latest run.
- `analyze_changed_paths` requires `changed_paths` or `git_diff_ref`.
- `changed_paths` is a structured `list[str]` of repo-relative paths, not a
  comma-separated string payload.
- `analyze_changed_paths` may return the same `run_id` as a previous run when
  the canonical report digest is unchanged; changed-files state is an overlay,
  not a second canonical report.
- `get_run_summary` with no `run_id` resolves to the latest stored run.
- `get_report_section(section="all")` returns the full canonical report document.
- `get_report_section(section="metrics")` returns only `metrics.summary`.
- `get_report_section(section="metrics_detail")` returns the full canonical
  metrics payload (`summary` + `families`).
- `get_report_section(section="changed")` is available only for diff-aware runs.
- `run_id` must equal the canonical report digest for that run.
- List-style MCP finding responses expose `base_uri` once per envelope instead
  of repeating absolute `file://` URIs inside summary/normal locations.
- Finding `locations` and `html_anchor` values are stable projections over the
  current run and do not invent non-canonical ids.
- For the same finding id, `source_kind` remains consistent across
  `list_findings`, `list_hotspots`, and `get_finding`.
- `get_finding` remains the compatibility-preserving full-detail endpoint:
  `priority_factors` and location `uri` are still available there.
- `compare_runs` is only semantically meaningful when both runs use comparable
  repository scope/root and analysis settings.

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
- `tests/test_mcp_service.py::test_mcp_service_changed_runs_remediation_and_review_flow`
- `tests/test_mcp_service.py::test_mcp_service_granular_checks_pr_summary_and_resources`
- `tests/test_mcp_service.py::test_mcp_service_evaluate_gates_on_existing_run`
- `tests/test_mcp_service.py::test_mcp_service_resources_expose_latest_summary_and_report`
- `tests/test_mcp_server.py::test_mcp_server_exposes_expected_read_only_tools`
- `tests/test_mcp_server.py::test_mcp_server_tool_roundtrip_and_resources`
- `tests/test_mcp_server.py::test_mcp_server_main_reports_missing_optional_dependency`

## Non-guarantees

- There is currently no standalone `mcp_api_version` constant.
- In-memory run history does not survive process restart.
- `clear_session_runs` resets the in-memory run registry and related session
  caches, but does not mutate baseline/cache/report artifacts on disk.
- Client-specific UI/approval behavior is not part of the CodeClone contract.

## See also

- [09-cli.md](09-cli.md)
- [08-report.md](08-report.md)
- [14-compatibility-and-versioning.md](14-compatibility-and-versioning.md)
- [../mcp.md](../mcp.md)
