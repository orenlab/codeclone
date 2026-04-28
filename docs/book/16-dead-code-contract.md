# 16. Dead Code Contract

## Purpose

Define dead-code liveness rules, canonical symbol-usage boundaries, and gating semantics.

## Public surface

- Dead-code detection core: `codeclone/metrics/dead_code.py:find_unused`
- Test-path classifier: `codeclone/paths.py:is_test_filepath`
- Inline suppression parser/binder: `codeclone/analysis/suppressions.py`
- Extraction of referenced names/candidates:
  `codeclone/analysis/units.py:extract_units_and_stats_from_source`
- Cache load boundary for referenced names:
  `codeclone/core/discovery_cache.py:load_cached_metrics_extended`

## Data model

- Candidate model: `DeadCandidate`
- Output model: `DeadItem` (`confidence=high|medium`)
- Global liveness input:
    - `referenced_names: frozenset[str]`
    - `referenced_qualnames: frozenset[str]`

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
- Module-level PEP 562 hooks are filtered as non-actionable:
  `__getattr__`, `__dir__`.
- Declaration-level inline suppression is supported with:
  `# codeclone: ignore[dead-code]` (leading or inline comment form).
- For multiline declaration headers, inline suppression may appear either on the
  first declaration line or on the closing header line containing `:`.
- Suppression is declaration-scoped (`def`, `async def`, `class`) and does not
  implicitly propagate to unrelated declaration targets.
- Candidate extraction excludes non-runtime declaration surfaces:
  methods on `Protocol` classes, and callables decorated with
  `@overload` / `@abstractmethod`.
- A symbol referenced by exact canonical qualname is not dead.
- A symbol referenced by local name is not dead.
- A symbol referenced only by qualified-name suffix (without canonical module
  match) downgrades confidence to `medium`.
- `--fail-dead-code` gate counts only high-confidence dead-code items.
- Suppressed dead-code candidates are excluded from active dead-code findings
  and from health-score dead-code penalties.
- Suppressed dead-code candidates are surfaced separately in report metrics
  (`dead_code.summary.suppressed`, `dead_code.suppressed_items`) and in the
  HTML dead-code split view (`Active` / `Suppressed`).

Refs:

- `codeclone/metrics/dead_code.py:_is_non_actionable_candidate`
- `codeclone/metrics/dead_code.py:find_unused`
- `codeclone/report/gates/evaluator.py:metric_gate_reasons`

## Invariants (MUST)

- Output dead-code items are deterministically sorted by
  `(filepath, start_line, end_line, qualname, kind)`.
- Test-path suppression is applied both on fresh extraction and cached-metrics
  load for both `referenced_names` and `referenced_qualnames`.

Refs:

- `codeclone/metrics/dead_code.py:find_unused`
- `codeclone/analysis/units.py:extract_units_and_stats_from_source`
- `codeclone/core/discovery_cache.py:load_cached_metrics_extended`

## Failure modes

| Condition                                          | Behavior                               |
|----------------------------------------------------|----------------------------------------|
| Dynamic method pattern (dunder/visitor/setup hook) | Candidate skipped as non-actionable    |
| Module PEP 562 hook (`__getattr__`/`__dir__`)      | Candidate skipped as non-actionable    |
| Malformed/unknown `# codeclone: ignore[...]` rule  | Ignored safely                         |
| Protocol or stub-like declaration surface          | Candidate skipped as non-actionable    |
| Definition appears only in tests                   | Candidate skipped                      |
| Symbol used only from tests                        | Remains actionable dead-code candidate |
| Symbol used through import alias / module alias    | Matched via canonical qualname usage   |
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
- `tests/test_extractor.py::test_dead_code_respects_runtime_hooks_and_inline_suppressions[skip_pep562_hooks]`
- `tests/test_extractor.py::test_dead_code_respects_runtime_hooks_and_inline_suppressions[inline_suppression_per_declaration]`
- `tests/test_extractor.py::test_dead_code_respects_runtime_hooks_and_inline_suppressions[suppression_binding_scoped_to_target]`
- `tests/test_extractor.py::test_extract_collects_referenced_qualnames_for_import_aliases`
- `tests/test_extractor.py::test_collect_dead_candidates_skips_protocol_and_stub_like_symbols`
- `tests/test_pipeline_metrics.py::test_load_cached_metrics_ignores_referenced_names_from_test_files`
- `tests/test_metrics_modules.py::test_find_unused_filters_non_actionable_and_preserves_ordering`
- `tests/test_metrics_modules.py::test_find_unused_respects_referenced_qualnames`
- `tests/test_metrics_modules.py::test_find_unused_keeps_non_pep562_module_dunders_actionable`
- `tests/test_metrics_modules.py::test_find_unused_applies_inline_dead_code_suppression`
- `tests/test_metrics_modules.py::test_find_suppressed_unused_returns_actionable_suppressed_candidates`
- `tests/test_report.py::test_report_json_dead_code_suppressed_items_are_reported_separately`
- `tests/test_html_report.py::test_html_report_renders_dead_code_split_with_suppressed_layer`
- `tests/test_suppressions.py::test_extract_suppression_directives_supports_inline_and_leading_forms`
- `tests/test_suppressions.py::test_bind_suppressions_targets_expected_declaration_scope[adjacent_leading_only]`

## Non-guarantees

- No full runtime call-graph resolution is performed.
- Medium-confidence dead items are informational and not used by
  `--fail-dead-code` gating.

## See also

- [05-core-pipeline.md](05-core-pipeline.md)
- [09-cli.md](09-cli.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
