# 20. MCP Interface

## Purpose

Define the current public MCP surface in the `2.0` beta line.

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
    - the `latest` pointer moves whenever a newer `analyze_*` call registers a run
- run identity:
    - canonical run identity is derived from the canonical report integrity digest
    - MCP payloads expose a short `run_id` handle (first 8 hex chars)
    - MCP tools/resources accept both short and full run ids
    - MCP finding ids are compact by default and may lengthen when needed to
      stay unique within a run
- analysis modes:
    - `full`
    - `clones_only`
- process-count policy:
    - `processes` is an optional override
    - when omitted, MCP defers to the core CodeClone runtime
- root contract:
    - analysis tools require an absolute repository root
    - relative roots such as `.` are rejected in MCP because server cwd may
      differ from the client workspace
    - granular `check_*` tools may omit `root` and use the latest compatible
      stored run; if `root` is provided, it must also be absolute
- cache policies:
    - `reuse`
    - `off`
      `refresh` is rejected in MCP because the server is read-only.
- summary payload:
    - `run_id`, `version`, `schema`, `mode`
    - `baseline`, `metrics_baseline`, `cache`
    - `cache.freshness` classifies summary cache reuse as `fresh`, `mixed`,
      or `reused`
    - flattened `inventory` (`files`, `lines`, `functions`, `classes`)
    - flattened `findings` (`total`, `new`, `known`, `by_family`, `production`)
    - flattened `diff` (`new_clones`, `health_delta`)
    - `warnings`, `failures`
    - `analyze_changed_paths` is intentionally more compact than `get_run_summary`:
      it returns `changed_files`, `health`, `health_delta`, `verdict`,
      `new_findings`, `resolved_findings`, and an empty `changed_findings`
      placeholder, while detailed changed payload stays in
      `get_report_section(section="changed")`
- finding-list payloads:
    - MCP finding ids are compact projection ids; canonical report ids are unchanged
    - `detail_level="summary"` is the default for list/check/hotspot tools
    - `detail_level="summary"` keeps compact relative `"path:line"` locations
    - `detail_level="normal"` keeps structured `{path, line, end_line, symbol}`
      locations plus remediation
    - `detail_level="full"` keeps the compatibility-oriented payload,
      including `priority_factors`, `items`, and per-location `uri`

The MCP layer does not introduce a separate analysis engine. It calls the
current CodeClone pipeline and reuses the canonical report document already
produced by the report contract.

## Tools

Current tool set:

| Tool                     | Key parameters                                                                                                                                         | Purpose / notes                                                                                                                                                                                                                                                                                  |
|--------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `analyze_repository`     | absolute `root`, `analysis_mode`, `changed_paths`, `git_diff_ref`, inline thresholds, cache/baseline paths                                             | Run deterministic CodeClone analysis, register the latest run, and return a compact MCP summary                                                                                                                                                                                                  |
| `analyze_changed_paths`  | absolute `root`, `changed_paths` or `git_diff_ref`, `analysis_mode`, inline thresholds                                                                 | Diff-aware fast path: analyze a repo, attach a changed-files projection, and return a compact changed-files snapshot                                                                                                                                                                             |
| `get_run_summary`        | `run_id`                                                                                                                                               | Return the stored summary for the latest or specified run, with slim inventory counts instead of the full file registry; `health` becomes explicit `available=false` when metrics were skipped                                                                                                   |
| `get_production_triage`  | `run_id`, `max_hotspots`, `max_suggestions`                                                                                                            | Return a compact production-first MCP projection: health, cache `freshness`, production hotspots, production suggestions, and global source-kind counters                                                                                                                                        |
| `compare_runs`           | `run_id_before`, `run_id_after`, `focus`                                                                                                               | Compare two registered runs by finding ids and run-to-run health delta; MCP returns short run ids, compact regression/improvement cards, `mixed` for conflicting signals, and `incomparable` with top-level `reason`, empty comparison cards, and `health_delta=null` when roots/settings differ |
| `evaluate_gates`         | `run_id`, gate thresholds/booleans                                                                                                                     | Evaluate CI/gating conditions against an existing run without exiting the process                                                                                                                                                                                                                |
| `get_report_section`     | `run_id`, `section`, `family`, `path`, `offset`, `limit`                                                                                               | Return a canonical report section. `metrics` is summary-only; `metrics_detail` is paginated/bounded and falls back to summary+hint when unfiltered                                                                                                                                               |
| `list_findings`          | `family`, `category`, `severity`, `source_kind`, `novelty`, `sort_by`, `detail_level`, `changed_paths`, `git_diff_ref`, `exclude_reviewed`, pagination | Return deterministically ordered finding groups with filtering and pagination; compact summary detail is the default                                                                                                                                                                             |
| `get_finding`            | `finding_id`, `run_id`, `detail_level`                                                                                                                 | Return one finding by id; defaults to `normal` detail and accepts MCP short ids                                                                                                                                                                                                                  |
| `get_remediation`        | `finding_id`, `run_id`, `detail_level`                                                                                                                 | Return just the remediation/explainability packet for one finding                                                                                                                                                                                                                                |
| `list_hotspots`          | `kind`, `run_id`, `detail_level`, `changed_paths`, `git_diff_ref`, `exclude_reviewed`, `limit`, `max_results`                                          | Return one derived hotlist (`most_actionable`, `highest_spread`, `highest_priority`, `production_hotspots`, `test_fixture_hotspots`) with compact summary cards                                                                                                                                  |
| `check_clones`           | `run_id`, `root`, `path`, `clone_type`, `source_kind`, `max_results`, `detail_level`                                                                   | Return clone findings from a compatible stored run; `health.dimensions` includes only `clones`                                                                                                                                                                                                   |
| `check_complexity`       | `run_id`, `root`, `path`, `min_complexity`, `max_results`, `detail_level`                                                                              | Return complexity hotspots from a compatible stored run; `health.dimensions` includes only `complexity`                                                                                                                                                                                          |
| `check_coupling`         | `run_id`, `root`, `path`, `max_results`, `detail_level`                                                                                                | Return coupling hotspots from a compatible stored run; `health.dimensions` includes only `coupling`                                                                                                                                                                                              |
| `check_cohesion`         | `run_id`, `root`, `path`, `max_results`, `detail_level`                                                                                                | Return cohesion hotspots from a compatible stored run; `health.dimensions` includes only `cohesion`                                                                                                                                                                                              |
| `check_dead_code`        | `run_id`, `root`, `path`, `min_severity`, `max_results`, `detail_level`                                                                                | Return dead-code findings from a compatible stored run; `health.dimensions` includes only `dead_code`                                                                                                                                                                                            |
| `generate_pr_summary`    | `run_id`, `changed_paths`, `git_diff_ref`, `format`                                                                                                    | Build a PR-friendly changed-files summary in markdown or JSON                                                                                                                                                                                                                                    |
| `mark_finding_reviewed`  | `finding_id`, `run_id`, `note`                                                                                                                         | Mark a finding as reviewed in the in-memory MCP session                                                                                                                                                                                                                                          |
| `list_reviewed_findings` | `run_id`                                                                                                                                               | Return the current reviewed findings for the selected run                                                                                                                                                                                                                                        |
| `clear_session_runs`     | none                                                                                                                                                   | Clear all stored in-memory runs plus ephemeral review/gate/session caches for the current server process                                                                                                                                                                                         |

All analysis/report tools are read-only with respect to repo state. The only
mutable MCP tools are `mark_finding_reviewed` and `clear_session_runs`, and
their effects are session-local and in-memory only. `analyze_repository`,
`analyze_changed_paths`, and `evaluate_gates` are
sessionful and may populate or reuse in-memory run state. The granular
`check_*` tools are read-only over stored runs: use `analyze_repository` or
`analyze_changed_paths` first, then query the latest run or pass a specific
`run_id`.

## Resources

Current fixed resources:

| Resource                         | Payload                                               | Availability                                          |
|----------------------------------|-------------------------------------------------------|-------------------------------------------------------|
| `codeclone://latest/summary`     | latest run summary projection                         | always after at least one run                         |
| `codeclone://latest/triage`      | latest production-first triage projection             | always after at least one run                         |
| `codeclone://latest/report.json` | latest canonical report document                      | always after at least one run                         |
| `codeclone://latest/health`      | latest health score + dimensions                      | always after at least one run                         |
| `codeclone://latest/gates`       | latest gate evaluation result                         | only after `evaluate_gates` in current server process |
| `codeclone://latest/changed`     | latest changed-files projection                       | only for a diff-aware latest run                      |
| `codeclone://schema`             | schema-style descriptor for canonical report sections | always available                                      |

Current run-scoped URI templates:

| URI template                                      | Payload                              | Availability                            |
|---------------------------------------------------|--------------------------------------|-----------------------------------------|
| `codeclone://runs/{run_id}/summary`               | run-specific summary projection      | for any stored run                      |
| `codeclone://runs/{run_id}/report.json`           | run-specific canonical report        | for any stored run                      |
| `codeclone://runs/{run_id}/findings/{finding_id}` | run-specific canonical finding group | for an existing finding in a stored run |

Fixed resources and URI templates are convenience views over already
registered runs. They do not trigger fresh analysis by themselves.
If a client needs the freshest truth, it must start a fresh analysis run first
(typically with `cache_policy="off"`), rather than relying on older session
state behind `codeclone://latest/...`.

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
- Inline MCP design-threshold parameters (`complexity_threshold`,
  `coupling_threshold`, `cohesion_threshold`) define the canonical design
  finding universe of that run and are recorded in
  `meta.analysis_thresholds.design_findings`.
- `get_run_summary` is a deterministic convenience projection derived from the
  canonical report (`meta`, `inventory`, `findings.summary`,
  `metrics.summary.health`) plus baseline-diff/gate/changed-files context.
- `get_production_triage` is also a deterministic MCP projection over the same
  canonical run state (`summary`, `derived.hotlists`, `derived.suggestions`,
  and canonical finding source scope). It must not create a second analysis or
  remediation truth path.
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
- `analyze_repository` and `analyze_changed_paths` require an absolute `root`;
  relative roots like `.` are rejected.
- `changed_paths` is a structured `list[str]` of repo-relative paths, not a
  comma-separated string payload.
- `analyze_changed_paths` may return the same `run_id` as a previous run when
  the canonical report digest is unchanged; changed-files state is an overlay,
  not a second canonical report.
- `get_run_summary` with no `run_id` resolves to the latest stored run.
- `codeclone://latest/...` resources always resolve to the latest stored run in
  the current MCP server process, not to a globally fresh analysis state.
- Summary-style MCP payloads expose `cache.freshness` as a derived convenience
  marker; canonical cache metadata remains available only through canonical
  report/meta surfaces.
- `get_report_section(section="all")` returns the full canonical report document.
- `get_report_section(section="metrics")` returns only `metrics.summary`.
- `get_report_section(section="metrics_detail")` is intentionally bounded:
  without filters it returns `summary` plus a hint; with `family` and/or `path`
  it returns a paginated item slice.
- `get_report_section(section="changed")` is available only for diff-aware runs.
- MCP short `run_id` values are session handles over the canonical digest of
  that run.
- MCP summary/normal finding/location payloads use relative paths only and do
  not expose absolute `file://` URIs.
- Finding `locations` and `html_anchor` values are stable projections over the
  current run and do not invent non-canonical ids.
- For the same finding id, `source_kind` remains consistent across
  `list_findings`, `list_hotspots`, and `get_finding`.
- `get_finding(detail_level="full")` remains the compatibility-preserving
  full-detail endpoint: `priority_factors` and location `uri` are still
  available there.
- `compare_runs` is only semantically meaningful when both runs use comparable
  repository scope/root and analysis settings.
- `compare_runs` exposes top-level `comparable` plus optional `reason`. When
  roots or effective analysis settings differ, `regressions` and
  `improvements` become empty lists, `unchanged` and `health_delta` become
  `null`, and `verdict` becomes `incomparable`.
- `compare_runs.health_delta` is `after.health - before.health` between the two
  selected comparable runs. It is independent of baseline or metrics-baseline
  drift.
- `compare_runs.verdict` is intentionally conservative but not one-dimensional:
  it returns `mixed` when run-to-run finding deltas and `health_delta` disagree.
- `analysis_mode="clones_only"` keeps clone findings fully usable, but MCP
  surfaces mark `health` as unavailable instead of fabricating zeroed metrics.
- `codeclone://latest/triage` is a latest-only resource; run-specific triage is
  available via the tool, not via a `codeclone://runs/{run_id}/...` resource URI.

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
- MCP must not re-synthesize design findings from raw metrics after the run;
  threshold-aware design findings belong to the canonical report document.

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
