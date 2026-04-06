# 20. MCP Interface

## Purpose

Define the current public MCP surface in the `2.0` beta line.

This interface is **optional** (installed via the `mcp` extra). It exposes
the deterministic analysis pipeline as a **read-only MCP server** for AI agents
and MCP-capable clients. It does not replace the CLI or the canonical report
contract.

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
- initialize metadata:
    - `serverInfo.version` reflects the CodeClone package version
    - clients may use it for compatibility checks
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
    - `run_id`, `version`, `schema`, `mode`, compact `analysis_profile`
    - `health_scope` explains what the health score covers
    - `focus` explains the active summary/triage lens
    - `baseline`, `metrics_baseline`, `cache`
    - `cache.freshness` classifies summary cache reuse as `fresh`, `mixed`,
      or `reused`
    - flattened `inventory` (`files`, `lines`, `functions`, `classes`)
    - flattened `findings` (`total`, `new`, `known`, `by_family`, `production`,
      `new_by_source_kind`)
    - flattened `diff` (`new_clones`, `health_delta`)
    - `warnings`, `failures`
    - `analyze_changed_paths` is intentionally more compact than `get_run_summary`:
      it returns `changed_files`, `focus`, `health_scope`, `health`,
      `health_delta`, `verdict`, `new_findings`, `new_by_source_kind`,
      `resolved_findings`, and an empty `changed_findings` placeholder, while
      detailed changed payload stays in
      `get_report_section(section="changed")`
- workflow guidance:
    - the MCP surface is intentionally agent-guiding rather than list-first
    - the cheapest useful path is designed to be the most obvious path:
      `get_run_summary` / `get_production_triage` first, then `list_hotspots`
      or `check_*`, then `get_finding` / `get_remediation`
    - `help(topic=...)` is a bounded semantic routing tool for contract/workflow
      uncertainty; it is not a second manual or docs proxy
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

Current tool set (`21` tools):

| Tool                     | Key parameters                                                                          | Purpose                                                                                            |
|--------------------------|-----------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| `analyze_repository`     | absolute `root`, `analysis_mode`, thresholds, cache/baseline paths                      | Full analysis → compact summary; then `get_run_summary` or `get_production_triage`                 |
| `analyze_changed_paths`  | absolute `root`, `changed_paths` or `git_diff_ref`, `analysis_mode`                     | Diff-aware analysis → compact changed-files snapshot                                               |
| `get_run_summary`        | `run_id`                                                                                | Cheapest run snapshot: health, findings, baseline, inventory, active thresholds                    |
| `get_production_triage`  | `run_id`, `max_hotspots`, `max_suggestions`                                             | Production-first view: health, hotspots, suggestions, active thresholds                            |
| `help`                   | `topic`, `detail`                                                                       | Semantic guide for workflow, analysis profile, baseline, suppressions, review state, changed-scope |
| `compare_runs`           | `run_id_before`, `run_id_after`, `focus`                                                | Run-to-run delta: regressions, improvements, health change                                         |
| `evaluate_gates`         | `run_id`, gate thresholds                                                               | Preview CI gating decisions                                                                        |
| `get_report_section`     | `run_id`, `section`, `family`, `path`, `offset`, `limit`                                | Read report sections; `metrics_detail` is paginated with family/path filters                       |
| `list_findings`          | `family`, `severity`, `novelty`, `sort_by`, `detail_level`, `changed_paths`, pagination | Filtered, paginated findings; use after hotspots or `check_*`                                      |
| `get_finding`            | `finding_id`, `run_id`, `detail_level`                                                  | Single finding detail by id; defaults to `normal`                                                  |
| `get_remediation`        | `finding_id`, `run_id`, `detail_level`                                                  | Remediation payload for one finding                                                                |
| `list_hotspots`          | `kind`, `run_id`, `detail_level`, `changed_paths`, `limit`                              | Priority-ranked hotspot views; preferred before broad listing                                      |
| `check_clones`           | `run_id`, `root`, `path`, `clone_type`, `source_kind`, `detail_level`                   | Clone findings only; `health.dimensions` includes only `clones`                                    |
| `check_complexity`       | `run_id`, `root`, `path`, `min_complexity`, `detail_level`                              | Complexity hotspots only                                                                           |
| `check_coupling`         | `run_id`, `root`, `path`, `detail_level`                                                | Coupling hotspots only                                                                             |
| `check_cohesion`         | `run_id`, `root`, `path`, `detail_level`                                                | Cohesion hotspots only                                                                             |
| `check_dead_code`        | `run_id`, `root`, `path`, `min_severity`, `detail_level`                                | Dead-code findings only                                                                            |
| `generate_pr_summary`    | `run_id`, `changed_paths`, `git_diff_ref`, `format`                                     | PR-friendly markdown or JSON summary                                                               |
| `mark_finding_reviewed`  | `finding_id`, `run_id`, `note`                                                          | Session-local review marker (in-memory)                                                            |
| `list_reviewed_findings` | `run_id`                                                                                | List reviewed findings for a run                                                                   |
| `clear_session_runs`     | none                                                                                    | Reset in-memory runs and session state                                                             |

All tools are read-only except `mark_finding_reviewed` and `clear_session_runs`
(session-local, in-memory). `check_*` tools query stored runs — call
`analyze_repository` or `analyze_changed_paths` first.

Recommended workflow:

1. `get_run_summary` or `get_production_triage`
2. `help(topic=...)` if contract meaning is unclear
3. `list_hotspots` or `check_*`
4. `get_finding` → `get_remediation`
5. `generate_pr_summary(format="markdown")`

For analysis sensitivity, the intended model is:

1. start with repo defaults or `pyproject`-resolved thresholds
2. lower thresholds only for an explicit higher-sensitivity exploratory pass
3. compare runs only when profile differences are understood

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
- `--allow-remote` expands the trust boundary materially:
    - any reachable network client can trigger CPU-intensive analysis
    - any reachable network client can read analysis results
    - request parameters such as `root` and path filters can still probe
      repository-relative filesystem structure
    - use it only on trusted networks or behind a firewall / authenticated
      reverse proxy
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
- `metrics_detail(family="overloaded_modules")` exposes the canonical report-only
  module-hotspot layer, but does not promote it into findings, hotlists, or
  gate semantics.
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
