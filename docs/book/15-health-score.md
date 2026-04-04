# Health Score

## Purpose

Define the current Health Score model, the report-only layers that do **not**
yet affect it, and the policy for future scoring-model expansion.

Health Score is a user-facing contract. It is not just an internal aggregate.

## Public surface

- Scoring model: `codeclone/metrics/health.py:compute_health`
- Weight assignment: `codeclone/contracts.py:HEALTH_WEIGHTS`
- Input wiring: `codeclone/pipeline.py:compute_project_metrics`
- Canonical report surface:
  `codeclone/report/json_contract.py:build_report_document`
- Overview projection:
  `codeclone/report/json_contract.py:_health_snapshot`
- CLI / HTML / MCP consumers:
  `codeclone/_cli_summary.py`, `codeclone/_html_report/_sections/_overview.py`,
  `codeclone/mcp_service.py`

## Contracts

- Health Score is computed only in `analysis_mode=full`.
- In `analysis_mode=clones_only`, health is intentionally unavailable rather
  than fabricated from partial inputs.
- The current scoring model includes exactly seven dimensions:
  `clones`, `complexity`, `coupling`, `cohesion`, `dead_code`,
  `dependencies`, `coverage`.
- Only dimensions produced by `compute_health(...)` contribute to the score.
- Report-only or advisory layers must not affect the score until they are
  explicitly promoted into the scoring model and documented.

## What currently affects Health Score

Current weights from `codeclone/contracts.py:HEALTH_WEIGHTS`:

| Dimension    | Weight | Current inputs in code                                                               | Signal type                      | Visible report/UI surface                                                                |
|--------------|--------|--------------------------------------------------------------------------------------|----------------------------------|------------------------------------------------------------------------------------------|
| Clones       | 25%    | function clone groups + block clone groups, normalized by `files_analyzed_or_cached` | aggregate project-level          | `metrics.families.health.summary.dimensions.clones`, HTML `Health Profile`, CLI, MCP     |
| Complexity   | 20%    | `complexity_avg`, `complexity_max`, `high_risk_functions`                            | local findings -> aggregate      | `metrics.families.health.summary.dimensions.complexity`, design findings, HTML, CLI, MCP |
| Cohesion     | 15%    | `cohesion_avg`, `low_cohesion_classes`                                               | local findings -> aggregate      | `metrics.families.health.summary.dimensions.cohesion`, design findings, HTML, CLI, MCP   |
| Coupling     | 10%    | `coupling_avg`, `coupling_max`, `high_risk_classes`                                  | local findings -> aggregate      | `metrics.families.health.summary.dimensions.coupling`, design findings, HTML, CLI, MCP   |
| Dead code    | 10%    | count of active dead-code items after suppression and non-actionable filtering       | local findings -> aggregate      | `metrics.families.dead_code`, health dimensions, HTML, CLI, MCP                          |
| Dependencies | 10%    | `dependency_cycles`, `dependency_max_depth`                                          | aggregate graph-level            | `metrics.families.dependencies`, health dimensions, HTML, CLI, MCP                       |
| Coverage     | 10%    | `files_analyzed_or_cached / files_found`                                             | aggregate inventory-completeness | `metrics.families.health.summary.dimensions.coverage`, HTML `Health Profile`, MCP        |

Important clarifications:

- `coverage` here means **analysis completeness**, not test coverage.
- The clone dimension currently uses only **function** and **block** clone
  groups. Segment groups are visible in reports, but they do not currently feed
  Health Score.
- Dead-code penalties use active dead-code items returned by
  `find_unused(...)`. Suppressed or non-actionable candidates do not penalize
  the score.
- Dependency pressure currently penalizes cycles directly and only penalizes
  dependency depth beyond the safe zone (`max_depth > 6`).

## Explainability intent

The current health model is deterministic and explainable by design:

- every scoring dimension is derived from explicit inputs already present in the
  pipeline and canonical report;
- the canonical report exposes the score and per-dimension breakdown under
  `metrics.families.health.summary`;
- overview/report projections may summarize the result, but they must not invent
  extra health heuristics outside the scoring model.

## Current non-scoring layers

The following layers are visible today but do **not** currently affect Health
Score:

### Overloaded Modules

`Overloaded Modules` is currently a report-only experimental layer.

- It surfaces module-level hotspots derived from implementation burden and
  dependency pressure.
- It is visible in `metrics.families.overloaded_modules`, HTML, Markdown/TXT, and MCP
  `metrics_detail(family="overloaded_modules")`.
- It does not currently affect Health Score, gates, baseline novelty, or SARIF.
- It is **not** a restatement of cyclomatic complexity: complexity highlights
  local control-flow hotspots, while Overloaded Modules highlights module-level
  responsibility overload and dependency pressure.

### Other visible non-scoring layers

- `findings.groups.clones.segments` — canonical report-only segment-clone layer;
  visible for review, excluded from baseline diff/gating/health.
- `findings.groups.structural.groups` — report-only structural findings;
  visible as evidence/advisory material, excluded from health.
- `derived.suggestions` and `derived.hotlists` — advisory and routing
  projections; never scoring inputs.

## Health model evolution

Health Score is stable within a given scoring model, but the model may evolve
across releases.

New signal families may first appear as report-only or experimental layers.
After validation and contract hardening, selected layers may later be
introduced into scoring.

Future CodeClone releases may expand the Health Score formula with additional
validated signal families. As a result, a repository's score may decrease after
upgrade even if the code itself did not become worse. In such cases, the change
reflects an evolved scoring model rather than a retroactive decline in code
quality.

Promotion rules for a new scoring input:

- the signal must be deterministic and stable enough for canonical reporting;
- the signal must be explainable in terms of explicit inputs and visible output;
- the signal must be validated on real repositories, not only synthetic cases;
- the change must be documented in release notes and in Health Score docs;
- MCP/HTML/CLI surfaces must continue to present the score honestly after the
  expansion.

Current versioning note:

- CodeClone does **not** currently define a separate health-model version
  constant.
- Health semantics are package-versioned public behavior and must therefore be
  documented in this chapter, in compatibility notes, and in release notes when
  they change.

## Locked by tests

- `tests/test_metrics_modules.py::test_health_helpers_and_compute_health_boundaries`
- `tests/test_pipeline_metrics.py::test_compute_project_metrics_respects_skip_flags`
- `tests/test_report_contract_coverage.py::test_report_contract_includes_canonical_overloaded_modules_family`
- `tests/test_report_contract_coverage.py::test_overview_health_snapshot_handles_non_mapping_dimensions`

## See also

- [08-report.md](08-report.md)
- [14-compatibility-and-versioning.md](14-compatibility-and-versioning.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
- [16-dead-code-contract.md](16-dead-code-contract.md)
