# 16. Dead Code Contract

## Purpose

Define dead-code liveness rules, test-path boundaries, and gating semantics.

## Public surface

- Dead-code detection core: `codeclone/metrics/dead_code.py:find_unused`
- Test-path classifier: `codeclone/paths.py:is_test_filepath`
- Extraction of referenced names/candidates:
  `codeclone/extractor.py:extract_units_and_stats_from_source`
- Cache load boundary for referenced names:
  `codeclone/pipeline.py:_load_cached_metrics`

## Data model

- Candidate model: `DeadCandidate`
- Output model: `DeadItem` (`confidence=high|medium`)
- Global liveness input:
  `referenced_names: frozenset[str]`

Refs:

- `codeclone/models.py:DeadCandidate`
- `codeclone/models.py:DeadItem`

## Contracts

- References from test files are excluded from liveness accounting.
- Symbols declared in test files are non-actionable and filtered.
- Symbols with names matching test entrypoint conventions are filtered:
  `test_*`, `pytest_*`.
- Methods are filtered as non-actionable when dynamic/runtime dispatch is
  expected:
  dunder methods, `visit_*`, setup/teardown hooks.
- A symbol referenced by local name is not dead.
- A symbol referenced only by qualified name downgrades confidence to `medium`.
- `--fail-dead-code` gate counts only high-confidence dead-code items.

Refs:

- `codeclone/metrics/dead_code.py:_is_non_actionable_candidate`
- `codeclone/metrics/dead_code.py:find_unused`
- `codeclone/pipeline.py:metric_gate_reasons`

## Invariants (MUST)

- Output dead-code items are deterministically sorted by
  `(filepath, start_line, end_line, qualname, kind)`.
- Test-path suppression is applied both on fresh extraction and cached-metrics
  load.

Refs:

- `codeclone/metrics/dead_code.py:find_unused`
- `codeclone/extractor.py:extract_units_and_stats_from_source`
- `codeclone/pipeline.py:_load_cached_metrics`

## Failure modes

| Condition                                          | Behavior                               |
|----------------------------------------------------|----------------------------------------|
| Dynamic method pattern (dunder/visitor/setup hook) | Candidate skipped as non-actionable    |
| Definition appears only in tests                   | Candidate skipped                      |
| Symbol used only from tests                        | Remains actionable dead-code candidate |
| `--fail-dead-code` with high-confidence dead items | Gating failure, exit `3`               |

## Determinism / canonicalization

- Filtering rules are deterministic string/path predicates.
- Candidate and result ordering is deterministic.

Refs:

- `codeclone/paths.py:is_test_filepath`
- `codeclone/metrics/dead_code.py:_is_dunder`
- `codeclone/metrics/dead_code.py:find_unused`

## Locked by tests

- `tests/test_extractor.py::test_dead_code_marks_symbol_dead_when_referenced_only_by_tests`
- `tests/test_pipeline_metrics.py::test_load_cached_metrics_ignores_referenced_names_from_test_files`
- `tests/test_metrics_modules.py::test_find_unused_filters_non_actionable_and_preserves_ordering`

## Non-guarantees

- No full runtime call-graph resolution is performed.
- Medium-confidence dead items are informational and not used by
  `--fail-dead-code` gating.

## See also

- [05-core-pipeline.md](05-core-pipeline.md)
- [09-cli.md](09-cli.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
