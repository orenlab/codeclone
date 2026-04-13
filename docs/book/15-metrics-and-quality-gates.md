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
- adoption threshold gates:
  `--min-typing-coverage`, `--min-docstring-coverage`
- external Cobertura coverage join:
  `--coverage FILE`, `--coverage-min PERCENT`,
  `--fail-on-untested-hotspots`
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
- `golden_fixture_paths` is a separate project-level clone policy:
  clone groups fully contained in matching `tests/` / `tests/fixtures/` paths
  are excluded before health/gate/suggestion evaluation, but remain visible as
  suppressed report facts.
- If metrics are not explicitly requested and no metrics baseline exists,
  runtime auto-enables clone-only mode (`skip_metrics=true`).
- In clone-only mode:
  `skip_dead_code=true`, `skip_dependencies=true`.
- `--fail-dead-code` forces dead-code analysis on (even if metrics are skipped).
- `--fail-cycles` forces dependency analysis on (even if metrics are skipped).
- Type/docstring adoption metrics are computed by default in full mode.
- `--coverage` joins an external Cobertura XML file to current-run function
  spans with stdlib XML parsing only. This signal is not metrics-baseline truth,
  is not written to `codeclone.baseline.json`, and does not affect fingerprint
  or clone identity semantics.
- Invalid Cobertura XML downgrades to a current-run
  `coverage_join.status="invalid"` signal in normal analysis. It does not fail
  the run or update any baseline; only `--fail-on-untested-hotspots` upgrades
  invalid input into a contract error.
- `--api-surface` is opt-in in normal runs, but runtime auto-enables it when
  `--fail-on-api-break` or `--update-metrics-baseline` needs a public API
  snapshot.
- In the normal CLI `Metrics` block, adoption coverage is shown whenever metrics
  are computed, and the public API surface line appears when `api_surface`
  facts were collected. A coverage line appears when `--coverage` produced a
  joined coverage summary.
- `--update-baseline` in full mode implies metrics-baseline update in the same
  run.
- If metrics baseline path equals clone baseline path and clone baseline file is
  missing, `--update-metrics-baseline` escalates to `--update-baseline` so
  embedded metrics can be written safely.
- `--fail-on-new-metrics` requires trusted metrics baseline unless baseline is
  being updated in the same run.
- `--fail-on-typing-regression` / `--fail-on-docstring-regression` require a
  metrics baseline that already contains adoption coverage data.
- `--fail-on-api-break` requires a metrics baseline that already contains
  `api_surface` data.
- `--fail-on-untested-hotspots` requires `--coverage` and a valid Cobertura XML
  input. It evaluates current-run `coverage_join` facts only for measured
  medium/high-risk functions below the configured threshold; scope gaps are
  surfaced separately and do not require or update a metrics baseline. The
  flag name is retained for CLI compatibility.
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
  threshold checks -> cycles/dead/health -> NEW-vs-baseline diffs ->
  adoption/API baseline diffs -> coverage-join hotspot gate.
- Metric gate reasons are namespaced as `metric:*` in gate output.

Refs:

- `codeclone/pipeline.py:metric_gate_reasons`
- `codeclone/pipeline.py:gate`

## Failure modes

| Condition                                                   | Behavior                             |
|-------------------------------------------------------------|--------------------------------------|
| `--skip-metrics` with metrics flags                         | Contract error, exit `2`             |
| `--fail-on-new-metrics` without trusted baseline            | Contract error, exit `2`             |
| Coverage/API regression gate without required baseline data | Contract error, exit `2`             |
| Invalid Cobertura XML without hotspot gate                  | Current-run invalid signal, exit `0` |
| Coverage hotspot gate without valid `--coverage` input      | Contract error, exit `2`             |
| `--update-metrics-baseline` when metrics were not computed  | Contract error, exit `2`             |
| Threshold breach or NEW-vs-baseline metric regressions      | Gating failure, exit `3`             |
| Coverage hotspots from current-run coverage join            | Gating failure, exit `3`             |

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
