# Authored-decision complexity debt

Tracker: **gh #61** (orenlab/codeclone) — targeted decomposition after v2.1.0a2.

## What this records

Wave D replaced the public `cyclomatic_complexity` metric with a source-level
**authored-decision count** (`codeclone.metrics.source_decisions`). Measured
under that metric, this repository carries real, un-waived complexity debt:
functions that contain many genuine authored decisions (`if`/`elif`, loops,
comprehension generators and filters, short-circuit boundaries, `except`
clauses, `match` cases and guards, `assert`).

This debt is **not a calibration defect and is not waived.** The Wave D
health-scale recalibration
(`codeclone.metrics.complexity_calibration`) made the health *scale* honest for
the new measurement contract; it did not remove any decision from any function.
The `>10` and `>20` tails below are retained here as measured structural debt so
that a3 decomposition is judged by the trajectory of this distribution, not by
"feels cleaner".

## Distribution snapshot (receipt)

Measured at the Wave D option-A landing, over the **production reference
population** — every production function/method (files outside `tests/` and
`benchmarks/`; nested local `def`s excluded; no clone floor), scored with
`source_decision_complexity` at `COMPLEXITY_ALGORITHM_REVISION = 3`. This is the
same population and procedure that generate the health reference permilles, so
the debt and the calibration read one measurement.

| Aggregate | Value |
|---|---:|
| Population (n) | 5438 |
| Mean | 3.90 |
| p50 / p90 / p95 / p99 | 3 / 8 / 11 / 21 |
| Functions > 10 authored decisions | **321** |
| Functions > 20 | **56** |
| Functions > 30 | **10** |
| Maximum | **98** |

Full analyzed population (what the health scorer measures, tests included,
n≈11700): 559 functions > 10 and 97 > 20. The `322` figure cited when the debt
was opened was a preliminary raw-AST walk that counted nested local `def`s as
units; the collector-based production figure above (321) supersedes it.

The machine-readable form of this snapshot is regenerable from
`complexity_calibration.debt_distribution_snapshot()` and the pinned
`COMPLEXITY_REFERENCE_DISTRIBUTION` histogram; the histogram is digest-pinned by
`tests/test_complexity_calibration.py`.

## Named worst offenders (decomposition entry points)

The single outlier, `report/document/metrics.py:_normalize_metrics_families`
(98 authored decisions in a ~1000-line normalization switchboard), alone spends
the whole 10-point health outlier term. It and the next tier
(`metrics/overloaded_modules.py:build_overloaded_modules_payload`,
`baseline/metrics_baseline.py:_snapshot`,
`observability/store/reader.py:_aggregates`,
`config/analytics.py:resolve_analytics_config`, all ~40) are the natural first
targets: per-family / per-section extraction genuinely lowers their authored
decision count.

## Rules for retiring this debt

- Decomposition must lower the **real** authored-decision count (genuine
  extraction), never game the metric. The single-owner guard in
  `tests/test_source_decisions.py` and the metric's honesty (independent recount
  parity) stand.
- Re-measuring this snapshot after decomposition is a **new measurement**;
  update this file and, if the health reference is re-derived, follow the
  `complexity_calibration` procedure with maintainer ratification.
- `fail_health` is a separate policy contract and is not moved here.
