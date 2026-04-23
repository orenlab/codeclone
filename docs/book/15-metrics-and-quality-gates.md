# 15. Metrics and Quality Gates

## Purpose

Define metrics mode selection, metrics-baseline behavior, and gating semantics.

## Public surface

- Metrics mode wiring: `codeclone/surfaces/cli/runtime.py:_configure_metrics_mode`
- Main orchestration and exit routing: `codeclone/surfaces/cli/workflow.py:_main_impl`
- Gate evaluation: `codeclone/report/gates/evaluator.py:metric_gate_reasons`,
  `codeclone/core/reporting.py:gate`
- Metrics baseline persistence/diff:
  `codeclone/baseline/metrics_baseline.py:MetricsBaseline`

## Data model

Metrics gate inputs:

- threshold gates:
  `--fail-complexity`, `--fail-coupling`, `--fail-cohesion`, `--fail-health`
- adoption threshold gates:
  `--min-typing-coverage`, `--min-docstring-coverage`
- current-run Cobertura coverage join:
  `--coverage`, `--coverage-min`, `--fail-on-untested-hotspots`
- boolean structural gates:
  `--fail-cycles`, `--fail-dead-code`
- baseline-aware delta gates:
  `--fail-on-new-metrics`,
  `--fail-on-typing-regression`,
  `--fail-on-docstring-regression`,
  `--fail-on-api-break`
- baseline update:
  `--update-metrics-baseline`
- opt-in metrics family:
  `--api-surface`

Modes:

- `analysis_mode=full`: metrics computed and suggestions enabled
- `analysis_mode=clones_only`: metrics skipped

Refs:

- `codeclone/surfaces/cli/runtime.py:_metrics_flags_requested`
- `codeclone/surfaces/cli/runtime.py:_metrics_computed`
- `codeclone/surfaces/cli/report_meta.py:_build_report_meta`
- `codeclone/metrics/health.py:compute_health`
- `codeclone/contracts/__init__.py:HEALTH_WEIGHTS`

## Contracts

- `--skip-metrics` is incompatible with metrics gating/update flags.
- If metrics are not explicitly requested and no metrics baseline exists, runtime may auto-enable clone-only mode.
- In clone-only mode, dead-code and dependency analysis are skipped unless explicitly forced by gates.
- There is currently no user-facing gate or config knob for `dependency_max_depth`;
  the metric is observed and contributes to Health Score through the internal
  health model only.
- `--coverage` is a current-run signal only; it does not update baseline state.
- Invalid Cobertura XML becomes `coverage_join.status="invalid"` in normal runs and becomes a contract error only when
  hotspot gating requires a valid join.
- `--api-surface` is opt-in, but runtime auto-enables it when API break gating or metrics-baseline update needs it.
- `--fail-on-new-metrics` requires a trusted metrics baseline unless baseline is being updated in the same run.
- `--fail-on-typing-regression`, `--fail-on-docstring-regression`, and `--fail-on-api-break` require the corresponding
  capability in the trusted metrics baseline.
- In CI mode, if a trusted metrics baseline is loaded, runtime enables `fail_on_new_metrics=true`.

Refs:

- `codeclone/surfaces/cli/runtime.py:_configure_metrics_mode`
- `codeclone/surfaces/cli/workflow.py:_main_impl`
- `codeclone/baseline/metrics_baseline.py:MetricsBaseline.verify_compatibility`

## Invariants (MUST)

- Metrics diff is computed only when metrics were computed and metrics baseline is trusted.
- Gate reasons are emitted in deterministic order.
- Metric gate reasons are namespaced as `metric:*`.

Refs:

- `codeclone/report/gates/evaluator.py:metric_gate_reasons`
- `codeclone/core/reporting.py:gate`

## Failure modes

| Condition                                                   | Behavior                             |
|-------------------------------------------------------------|--------------------------------------|
| `--skip-metrics` with metrics flags                         | Contract error, exit `2`             |
| `--fail-on-new-metrics` without trusted baseline            | Contract error, exit `2`             |
| Coverage/API regression gate without required baseline data | Contract error, exit `2`             |
| Invalid Cobertura XML without hotspot gate                  | Current-run invalid signal, exit `0` |
| Coverage hotspot gate without valid `--coverage` input      | Contract error, exit `2`             |
| `--update-metrics-baseline` when metrics were not computed  | Contract error, exit `2`             |
| Threshold breach or metrics regressions                     | Gating failure, exit `3`             |

## Determinism / canonicalization

- Metrics baseline snapshot fields are canonicalized and sorted where set-like.
- Metrics payload hash uses canonical JSON and constant-time comparison.
- Gate reason generation order is fixed by code path order.

Refs:

- `codeclone/baseline/_metrics_baseline_payload.py:snapshot_from_project_metrics`
- `codeclone/baseline/_metrics_baseline_payload.py:_compute_payload_sha256`
- `codeclone/baseline/metrics_baseline.py:MetricsBaseline.verify_integrity`

## Locked by tests

- `tests/test_cli_unit.py::test_configure_metrics_mode_rejects_skip_metrics_with_metrics_flags`
- `tests/test_cli_unit.py::test_main_impl_rejects_update_metrics_baseline_when_metrics_skipped`
- `tests/test_cli_unit.py::test_main_impl_fail_on_new_metrics_requires_existing_baseline`
- `tests/test_cli_unit.py::test_main_impl_ci_enables_fail_on_new_metrics_when_metrics_baseline_loaded`
- `tests/test_pipeline_metrics.py::test_metric_gate_reasons_collects_all_enabled_reasons`
- `tests/test_pipeline_metrics.py::test_metric_gate_reasons_partial_new_metrics_paths`
- `tests/test_metrics_baseline.py::test_metrics_baseline_embedded_clone_payload_and_schema_resolution`

## Non-guarantees

- Absolute threshold defaults are not frozen by this chapter.
- Metrics scoring internals may evolve if exit semantics and contract statuses stay stable and are documented honestly.
