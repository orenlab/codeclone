# 15. Metrics and Quality Gates

## Purpose

Define metrics mode selection, metrics-baseline behavior, and gating semantics.

## Public surface

- Metrics mode wiring: `codeclone/cli.py:_configure_metrics_mode`
- Main orchestration and exit routing: `codeclone/cli.py:_main_impl`
- Gate evaluation: `codeclone/pipeline.py:metric_gate_reasons`,
  `codeclone/pipeline.py:gate`
- Metrics baseline persistence/diff: `codeclone/metrics_baseline.py:MetricsBaseline`

## Data model

Metrics gate inputs:

- threshold gates:
  `--fail-complexity`, `--fail-coupling`, `--fail-cohesion`, `--fail-health`
- boolean structural gates:
  `--fail-cycles`, `--fail-dead-code`
- delta gate:
  `--fail-on-new-metrics`
- baseline update:
  `--update-metrics-baseline`

Modes:

- `analysis_mode=full`: metrics computed and suggestions enabled
- `analysis_mode=clones_only`: metrics skipped
- Health-score semantics are defined in
  [15-health-score.md](15-health-score.md).
- Metrics comparison state is unified by default: unless `--metrics-baseline`
  is explicitly redirected, metrics baseline data comes from the same
  `codeclone.baseline.json` path as clone baseline data.

Refs:

- `codeclone/cli.py:_metrics_flags_requested`
- `codeclone/cli.py:_metrics_computed`
- `codeclone/_cli_meta.py:_build_report_meta`
- `codeclone/metrics/health.py:compute_health`
- `codeclone/contracts.py:HEALTH_WEIGHTS`

## Contracts

- `--skip-metrics` is incompatible with metrics gating/update flags and is a
  contract error.
- If metrics are not explicitly requested and no metrics baseline exists,
  runtime auto-enables clone-only mode (`skip_metrics=true`).
- In clone-only mode:
  `skip_dead_code=true`, `skip_dependencies=true`.
- `--fail-dead-code` forces dead-code analysis on (even if metrics are skipped).
- `--fail-cycles` forces dependency analysis on (even if metrics are skipped).
- `--update-baseline` in full mode implies metrics-baseline update in the same
  run.
- If metrics baseline path equals clone baseline path and clone baseline file is
  missing, `--update-metrics-baseline` escalates to `--update-baseline` so
  embedded metrics can be written safely.
- `--fail-on-new-metrics` requires trusted metrics baseline unless baseline is
  being updated in the same run.
- In CI mode, if metrics baseline was loaded and trusted, runtime enables
  `fail_on_new_metrics=true`.

Refs:

- `codeclone/cli.py:_configure_metrics_mode`
- `codeclone/cli.py:_main_impl`
- `codeclone/metrics_baseline.py:MetricsBaseline.verify_compatibility`

## Invariants (MUST)

- Metrics diff is computed only when:
  metrics were computed and metrics baseline is trusted.
- Metric gate reasons are emitted in deterministic order:
  threshold checks -> cycles/dead/health -> NEW-vs-baseline diffs.
- Metric gate reasons are namespaced as `metric:*` in gate output.

Refs:

- `codeclone/pipeline.py:metric_gate_reasons`
- `codeclone/pipeline.py:gate`

## Failure modes

| Condition                                                  | Behavior                 |
|------------------------------------------------------------|--------------------------|
| `--skip-metrics` with metrics flags                        | Contract error, exit `2` |
| `--fail-on-new-metrics` without trusted baseline           | Contract error, exit `2` |
| `--update-metrics-baseline` when metrics were not computed | Contract error, exit `2` |
| Threshold breach or NEW-vs-baseline metric regressions     | Gating failure, exit `3` |

## Determinism / canonicalization

- Metrics baseline snapshot fields are canonicalized and sorted where set-like.
- Metrics payload hash uses canonical JSON and constant-time comparison.
- Gate reason generation order is fixed by code path order.

Refs:

- `codeclone/metrics_baseline.py:snapshot_from_project_metrics`
- `codeclone/metrics_baseline.py:_compute_payload_sha256`
- `codeclone/metrics_baseline.py:MetricsBaseline.verify_integrity`

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
- Metrics scoring internals, per-dimension weighting, and the exact clone
  density curve may evolve if exit semantics and contract statuses stay stable.
  See [15-health-score.md](15-health-score.md) for the current model and the
  phased expansion policy.

## See also

- [15-health-score.md](15-health-score.md)
- [04-config-and-defaults.md](04-config-and-defaults.md)
- [05-core-pipeline.md](05-core-pipeline.md)
- [09-cli.md](09-cli.md)
- [16-dead-code-contract.md](16-dead-code-contract.md)
- [17-suggestions-and-clone-typing.md](17-suggestions-and-clone-typing.md)
