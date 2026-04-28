# 05. Core Pipeline

## Purpose

Describe the runtime pipeline from file discovery to grouped clones, metrics,
report assembly, and gating.

## Public surface

- Discovery: `codeclone/core/discovery.py:discover`
- Per-file processing: `codeclone/core/worker.py:process_file`
- Extraction: `codeclone/analysis/units.py:extract_units_and_stats_from_source`
- Clone grouping: `codeclone/findings/clones/grouping.py`
- Project metrics and suggestions: `codeclone/core/pipeline.py`
- Report/gating integration: `codeclone/core/reporting.py:report`,
  `codeclone/core/reporting.py:gate`

## Data model

Stages:

1. Bootstrap runtime paths and config.
2. Discover Python files with deterministic traversal.
3. Load usable cache entries by stat signature and compatible analysis profile.
4. Process changed/missed files:
    - read source
    - parse AST with limits
    - extract function, block, and segment units
    - collect referenced names/qualnames and dead-code candidates
5. Build groups:
    - function groups by `fingerprint|loc_bucket`
    - block groups by `block_hash`
    - segment groups by `segment_sig` then `segment_hash|qualname`
6. Compute project metrics in full mode:
    - complexity, coupling, cohesion
    - dead code
    - dependency graph and cycles
    - health score
    - adoption, API surface, optional coverage join
7. Build canonical report document and deterministic projections.
8. Evaluate clone diff and metric gates.

Refs:

- `codeclone/core/bootstrap.py:bootstrap`
- `codeclone/core/discovery.py:discover`
- `codeclone/core/worker.py:process_file`
- `codeclone/analysis/units.py:extract_units_and_stats_from_source`
- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/report/gates/evaluator.py:metric_gate_reasons`
- `codeclone/core/reporting.py:gate`

## Contracts

- Detection core computes facts; report layer materializes canonical findings from those facts.
- Report-layer transformations do not change function/block grouping keys used for baseline diff.
- Segment groups are report-only and do not participate in baseline diff/gating.
- Structural findings are report-only and do not participate in baseline diff/gating.
- `golden_fixture_paths` is a clone-policy exclusion layer:
  excluded groups remain visible as suppressed canonical report facts, but do
  not affect health, gates, or suggestions.
- Test-path liveness references are filtered both on fresh extraction and on
  cache decode.

Refs:

- `codeclone/findings/clones/grouping.py:build_groups`
- `codeclone/report/document/_findings_groups.py:_build_clone_groups`
- `codeclone/findings/structural/detectors.py:normalize_structural_findings`
- `codeclone/core/discovery_cache.py:load_cached_metrics_extended`
- `codeclone/baseline/clone_baseline.py:Baseline.diff`

## Invariants (MUST)

- `files_found = files_analyzed + cache_hits + files_skipped`, or CLI warns explicitly.
- In gating mode, unreadable source IO is a contract failure.
- Parser time/resource protections are applied before AST extraction.

Refs:

- `codeclone/surfaces/cli/summary.py:_print_summary`
- `codeclone/surfaces/cli/workflow.py:_main_impl`
- `codeclone/analysis/parser.py:_parse_limits`

## Failure modes

| Condition                        | Behavior                                         |
|----------------------------------|--------------------------------------------------|
| File stat/read/encoding error    | File skipped; tracked as failed file             |
| Source read error in gating mode | Contract error, exit `2`                         |
| Parser timeout                   | `ParseError` through processing failure path     |
| Unexpected per-file exception    | Captured as `unexpected_error` processing result |

## Determinism / canonicalization

- File list is sorted.
- Group sorting is deterministic by stable tuple keys.
- Canonical report integrity is computed only from canonical sections.

Refs:

- `codeclone/scanner.py:iter_py_files`
- `codeclone/findings/clones/grouping.py:build_groups`
- `codeclone/report/document/integrity.py:_build_integrity_payload`

## Locked by tests

- `tests/test_scanner_extra.py::test_iter_py_files_deterministic_sorted_order`
- `tests/test_cli_inprocess.py::test_cli_summary_cache_miss_metrics`
- `tests/test_cli_inprocess.py::test_cli_unreadable_source_fails_in_ci_with_contract_error`
- `tests/test_extractor.py::test_parse_limits_triggers_timeout`
- `tests/test_extractor.py::test_dead_code_marks_symbol_dead_when_referenced_only_by_tests`
- `tests/test_pipeline_metrics.py::test_load_cached_metrics_ignores_referenced_names_from_test_files`

## Non-guarantees

- Parallel worker scheduling order is not guaranteed; only final output determinism is guaranteed.
