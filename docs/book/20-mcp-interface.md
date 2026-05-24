# 20. MCP Interface

## Purpose

Define the current public MCP surface in the CodeClone `2.1` release line.

The MCP layer is optional, read-only, and built on the same canonical
pipeline/report contracts as the CLI. It does not create a second analysis
engine or a second persistence model.

!!! note "Read-only integration contract"
    MCP surfaces the same canonical report and run state as the CLI and HTML
    report. It must not mutate source, baseline, cache, or report artifacts.

## Public surface

- package extra: `codeclone[mcp]`
- launcher: `codeclone-mcp`
- server wiring: `codeclone/surfaces/mcp/server.py`
- in-process service/session: `codeclone/surfaces/mcp/service.py`,
  `codeclone/surfaces/mcp/session.py`

## Shape

Current server characteristics:

- optional dependency; base `codeclone` install does not require MCP runtime
- transports:
    - `stdio`
    - `streamable-http`
- run storage:
    - in-memory only
    - bounded by `--history-limit`
    - latest-run pointer is process-local
- roots:
    - analysis tools require an absolute repository root
    - relative roots such as `.` are rejected
- analysis modes:
    - `full`
    - `clones_only`
- cache policies:
    - `reuse`
    - `off`
    - `refresh` is rejected by the read-only MCP service contract; use `reuse`
      or `off`

!!! warning "Absolute roots and remote exposure"
    Analysis tools require an absolute repository root, and HTTP exposure
    beyond loopback is intentionally explicit. Keep `stdio` as the default for
    local IDE and agent clients.

## Tools

Current tool set: `25` tools.

The MCP surface is intentionally triage-first: analyze first, summarize/triage
second, then drill into one finding or one hotspot family.

`get_blast_radius` keeps hard guardrails separate from review context.
`do_not_touch` is limited to actionable negative context such as baselines,
generated CodeClone state, and explicit forbidden paths. Report-only signals
such as security boundary inventory and overloaded-module candidates are
returned as `review_context`, not as edit prohibitions. Long context sections
include `total`, `shown`, and `truncated` summaries.

`manage_change_intent` is session-local for intent truth, but v2.1 also writes
best-effort workspace coordination records under `.cache/codeclone/intents/`.
Those records are advisory multi-agent visibility only; MCP still never updates
source files, baselines, reports, or analysis cache data.

`create_review_receipt` is a read-only audit artifact. It composes stored
report provenance, optional intent/blast-radius state, reviewed findings,
structural delta, patch-contract status, human decision points, and
claims-not-made into markdown or JSON. It does not enter report integrity and
does not persist outside the MCP session.

### Analysis and run-level tools

| Tool                    | Key parameters                                                                                                               | Purpose                                                                                                                                                  |
|-------------------------|------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `analyze_repository`    | `root`, `analysis_mode`, thresholds, `api_surface`, `coverage_xml`, `baseline_path`, `metrics_baseline_path`, `cache_policy` | Full deterministic analysis of one repo root; registers the latest in-memory run.                                                                        |
| `analyze_changed_paths` | `root`, `changed_paths` or `git_diff_ref`, `analysis_mode`, thresholds, `api_surface`, `coverage_xml`, `cache_policy`        | Diff-aware analysis with changed-files projection over the same canonical run/report contract.                                                           |
| `get_run_summary`       | `run_id`                                                                                                                     | Cheapest run-level snapshot. Start here after analysis when you need health, findings, baseline/cache status, and inventory in compact form.             |
| `get_production_triage` | `run_id`, `max_hotspots`, `max_suggestions`                                                                                  | Production-first first-pass view over one stored run.                                                                                                    |
| `get_blast_radius`      | `run_id`, `files`, `depth`, `include`                                                                                        | Derived pre-change risk boundary: direct dependents, clone cohorts, coverage gaps, risk signals, actionable do-not-touch paths, and review-only context. |
| `check_patch_contract`  | `mode`, `run_id`, `before_run_id`, `after_run_id`, `intent_id`, `strictness`, `changed_files` or `diff_ref`                  | Pre-edit regression budget or post-edit verification over stored runs, gate evaluation, change intent scope, and baseline-abuse signals.                 |
| `create_review_receipt` | `run_id`, `intent_id`, `format`, `include_blast_radius`, `include_patch_contract`                                             | Deterministic audit artifact over stored run/session state; returns markdown or JSON without mutating artifacts.                                         |
| `help`                  | `topic`, `detail`                                                                                                            | Bounded workflow/contract guidance for supported MCP topics.                                                                                             |
| `compare_runs`          | `run_id_before`, `run_id_after`, `focus`                                                                                     | Run-to-run delta view over findings and health; returns `incomparable` when roots/settings differ.                                                       |
| `evaluate_gates`        | `run_id`, gate flags, threshold overrides, `coverage_min`                                                                    | Evaluate CI/gating decisions against a stored run without mutating process or repo state.                                                                |

### Report and finding projection tools

| Tool                  | Key parameters                                                                                                                     | Purpose                                                                                    |
|-----------------------|------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| `get_report_section`  | `run_id`, `section`, `family`, `path`, `offset`, `limit`                                                                           | Read canonical report sections; `metrics_detail` is the bounded/paginated drill-down path. |
| `list_findings`       | `run_id`, `family`, `category`, `severity`, `source_kind`, `novelty`, `sort_by`, `detail_level`, changed-scope filters, pagination | Deterministic filtered finding list over canonical stored findings.                        |
| `get_finding`         | `finding_id`, `run_id`, `detail_level`                                                                                             | Return one canonical finding group by short or full id.                                    |
| `get_remediation`     | `finding_id`, `run_id`, `detail_level`                                                                                             | Return the remediation/explainability packet for one finding.                              |
| `list_hotspots`       | `kind`, `run_id`, `detail_level`, changed-scope filters, pagination                                                                | Return one derived hotspot list such as `most_actionable` or `production_hotspots`.        |
| `generate_pr_summary` | `run_id`, `changed_paths`, `git_diff_ref`, `format`                                                                                | PR-oriented summary for changed scope; `markdown` is the default human/LLM-facing format.  |

### Focused check tools

| Tool               | Key parameters                                                                                  | Purpose                                               |
|--------------------|-------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| `check_clones`     | `run_id` or absolute `root`, `path`, `clone_type`, `source_kind`, `max_results`, `detail_level` | Narrow clone-only query over a compatible stored run. |
| `check_complexity` | `run_id` or absolute `root`, `path`, `min_complexity`, `max_results`, `detail_level`            | Narrow complexity-hotspot query.                      |
| `check_coupling`   | `run_id` or absolute `root`, `path`, `max_results`, `detail_level`                              | Narrow coupling-hotspot query.                        |
| `check_cohesion`   | `run_id` or absolute `root`, `path`, `max_results`, `detail_level`                              | Narrow cohesion-hotspot query.                        |
| `check_dead_code`  | `run_id` or absolute `root`, `path`, `min_severity`, `max_results`, `detail_level`              | Narrow dead-code query.                               |

### Session-local tools

| Tool                     | Key parameters                                                          | Purpose                                                                             |
|--------------------------|-------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| `mark_finding_reviewed`  | `finding_id`, `run_id`, `note`                                          | Mark a finding as reviewed in the current in-memory MCP session.                    |
| `list_reviewed_findings` | `run_id`                                                                | Return reviewed markers currently held in process memory.                           |
| `manage_change_intent`   | `action`, `root`, `run_id`, `intent_id`, `scope`, `ttl_seconds`, `changed_files` or `diff_ref` | Declare/check/clear session-local intent and list/gc/reset workspace coordination records. |
| `clear_session_runs`     | none                                                                    | Clear in-memory run history and session-local review state for this server process. |

## Resources

Resources are deterministic read-only projections over stored runs.

| URI                                               | Purpose                                                     |
|---------------------------------------------------|-------------------------------------------------------------|
| `codeclone://latest/summary`                      | Compact summary for the latest stored run.                  |
| `codeclone://latest/report.json`                  | Canonical JSON report for the latest stored run.            |
| `codeclone://latest/health`                       | Health/metrics snapshot for the latest stored run.          |
| `codeclone://latest/gates`                        | Last gate-evaluation result produced in this MCP session.   |
| `codeclone://latest/changed`                      | Changed-files projection for the latest diff-aware run.     |
| `codeclone://latest/triage`                       | Production-first triage payload for the latest stored run.  |
| `codeclone://schema`                              | Canonical report schema-style descriptor.                   |
| `codeclone://runs/{run_id}/summary`               | Compact summary for one specific stored run.                |
| `codeclone://runs/{run_id}/report.json`           | Canonical JSON report for one specific stored run.          |
| `codeclone://runs/{run_id}/findings/{finding_id}` | Canonical JSON finding payload for one specific stored run. |

## Contract rules

- MCP is read-only with respect to source files, baselines, analysis cache
  artifacts such as `cache.json`, and report artifacts.
- MCP reuses the same canonical report document as CLI/JSON/HTML/SARIF.
- Finding ids, ordering, and summary data are deterministic projections over
  the stored run.
- `analyze_changed_paths` requires either explicit `changed_paths` or
  `git_diff_ref`.
- `analyze_repository` and `analyze_changed_paths` require an absolute `root`.
- `check_*` tools may resolve against an existing stored run, but if `root` is
  provided it must also be absolute.
- `git_diff_ref` is validated before any subprocess call.
- Review markers are session-local in-memory state only.
- Change intent and blast-radius cache state are session-local in-memory state
  only; they do not enter canonical report integrity, baseline, or cache
  artifacts.
- Run history is process-local and does not survive restart.
- Missing optional MCP dependency is surfaced explicitly by the launcher.
- `metrics_detail(family="security_surfaces")` exposes a compact, report-only
  inventory of exact security-relevant capability surfaces. It does not claim
  vulnerabilities or exploitability.

## Security model

- default transport is local `stdio`
- non-local HTTP exposure requires explicit `--allow-remote`
- server runtime is loaded lazily so base installs and normal CI do not require
  MCP packages
- MCP must not mutate repo state or synthesize findings outside canonical
  report facts

## Determinism

- run identity is derived from canonical report integrity
- summary, hotspots, findings, and remediation payloads are deterministic
  projections over stored run state
- MCP must not create MCP-only analysis semantics or MCP-only gate semantics

## Locked by tests

- `tests/test_mcp_service.py`
- `tests/test_mcp_server.py`
- `tests/test_mcp_tool_schema_snapshot.py`

## See also

- [09-cli.md](09-cli.md)
- [08-report.md](08-report.md)
- [14-compatibility-and-versioning.md](14-compatibility-and-versioning.md)
- [../mcp.md](../mcp.md)
