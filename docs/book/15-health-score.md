# Health Score

## Purpose

Define the current Health Score model, what does not affect it yet, and the
policy for future scoring-model expansion.

## Public surface

- Scoring model: `codeclone/metrics/health.py:compute_health`
- Weight assignment: `codeclone/contracts/__init__.py:HEALTH_WEIGHTS`
- Input wiring: `codeclone/core/pipeline.py:compute_project_metrics`
- Canonical report surface:
  `codeclone/report/document/builder.py:build_report_document`
- Health snapshot projections:
  `codeclone/report/derived.py:_health_snapshot`,
  `codeclone/report/overview.py:_health_snapshot`
- CLI / HTML / MCP consumers:
  `codeclone/surfaces/cli/summary.py`,
  `codeclone/report/html/sections/_overview.py`,
  `codeclone/surfaces/mcp/session.py`

## Contracts

- Health Score is computed only in `analysis_mode=full`.
- In `analysis_mode=clones_only`, health is intentionally unavailable.
- The current scoring model includes exactly seven dimensions:
  `clones`, `complexity`, `coupling`, `cohesion`, `dead_code`,
  `dependencies`, `coverage`.
- Report-only or advisory layers must not affect the score until they are explicitly promoted and documented.

## What currently affects Health Score

Current weights from `codeclone/contracts/__init__.py:HEALTH_WEIGHTS`:

| Dimension    | Weight | Signal                                                           |
|--------------|--------|------------------------------------------------------------------|
| Clones       | 25%    | Function + block clone density                                   |
| Complexity   | 20%    | Function-level complexity risk                                   |
| Cohesion     | 15%    | Low-cohesion class pressure                                      |
| Coupling     | 10%    | Class-level coupling pressure                                    |
| Dead code    | 10%    | Active dead-code items after suppression/filtering               |
| Dependencies | 10%    | Cycles and deep dependency chains                                |
| Coverage     | 10%    | Analysis completeness (`files_analyzed_or_cached / files_found`) |

Important clarifications:

- `coverage` here means analysis completeness, not test coverage.
- Segment clones are visible in reports but do not currently affect Health Score.
- Suppressed or non-actionable dead-code items do not penalize the score.
- Dependencies score uses the internal module dependency graph only.
- Cycles still penalize the dependencies dimension directly.
- Acyclic depth pressure is adaptive:
  `expected_tail = max(ceil(avg_depth * 2.0), p95_depth + 1)`, then
  `tail_pressure = max(0, max_depth - expected_tail)`.
- The dependencies dimension score is:
  `100 - cycles * 25 - tail_pressure * 4`.
- This model is internal and not configurable through CLI or `pyproject.toml`.

## Current non-scoring layers

Visible but non-scoring:

- `metrics.families.overloaded_modules`
- `findings.groups.clones.segments`
- `findings.groups.structural.groups`
- `derived.suggestions`
- `derived.hotlists`
- `metrics.families.coverage_join`

## Health model evolution

Future releases may expand the score with additional validated signal families.
If that happens:

- the change must be documented in this chapter and release notes
- CLI/HTML/MCP must continue to present the score honestly
- a lower score after upgrade may reflect a broader model, not only worse code

## Locked by tests

- `tests/test_metrics_modules.py::test_health_helpers_and_compute_health_boundaries`
- `tests/test_pipeline_metrics.py::test_compute_project_metrics_respects_skip_flags`
- `tests/test_report_contract_coverage.py::test_report_contract_includes_canonical_overloaded_modules_family`
- `tests/test_report_contract_coverage.py::test_overview_health_snapshot_handles_non_mapping_dimensions`

## See also

- [08-report.md](08-report.md)
- [14-compatibility-and-versioning.md](14-compatibility-and-versioning.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
