# 19. Inline Suppressions

## Purpose

Define deterministic local suppressions for known findings false positives via
source comments, without introducing broad/project-wide ignores.

## Public surface

- Suppression directive parser and binder: `codeclone/suppressions.py`
- Dead-code final filter: `codeclone/metrics/dead_code.py:find_unused`
- Suppressed dead-code projection helper:
  `codeclone/metrics/dead_code.py:find_suppressed_unused`
- Dead-code candidate extraction: `codeclone/extractor.py:_collect_dead_candidates`

## Data model

- Directive model: `SuppressionDirective` (`line`, `binding`, `rules`)
- Declaration target model: `DeclarationTarget`
- Bound suppression model: `SuppressionBinding`
- Candidate storage: `DeadCandidate.suppressed_rules`

Refs:

- `codeclone/suppressions.py:SuppressionDirective`
- `codeclone/suppressions.py:DeclarationTarget`
- `codeclone/suppressions.py:SuppressionBinding`
- `codeclone/models.py:DeadCandidate`

## Contracts

- Canonical syntax: `# codeclone: ignore[<rule-id>]`
- Supported placements:
    - previous line before declaration (`leading`)
    - end-of-line comment on declaration header (`inline`)
      - same-line single-line declaration
      - first line of a multiline declaration header
      - closing header line containing `:`
- Current supported dead-code rule id: `dead-code`.
- Rule list supports comma-separated values and deduplicates deterministically.
- Suppression applies only to declaration targets (`def`, `async def`, `class`).
- Suppression is target-scoped:
  class-level suppression does not implicitly suppress unrelated methods.
- Dead-code suppression is applied in final liveness filtering by rule id.
- Suppressed dead-code candidates are reported separately (not as active
  findings) with deterministic suppression metadata in report metrics.

## Invariants (MUST)

- If no `# codeclone: ignore[...]` exists, behavior remains unchanged.
- Suppression matching never jumps across non-adjacent lines.
- Unknown/malformed suppressions never fail analysis.
- Suppression handling remains deterministic under identical inputs.

## Failure modes

| Condition                                         | Behavior                            |
|---------------------------------------------------|-------------------------------------|
| malformed `# codeclone: ignore[...]` payload      | ignored silently                    |
| unknown `codeclone[...]` rule id                  | ignored silently                    |
| suppression on non-declaration line               | ignored silently                    |
| duplicate rule ids in one directive               | deduplicated deterministically      |
| suppression rule mismatch (`dead-code` vs others) | does not suppress dead-code finding |

## Determinism / canonicalization

- Directives are parsed from lexical comment tokens, not heuristic substring
  scans.
- Binding is deterministic by declaration line and target identity.
- Inline binding for multiline declarations is deterministic across the
  declaration header span only; it does not search arbitrary body lines.
- Candidate-level `suppressed_rules` are canonicalized and sorted in cache
  payloads.
- Report-level suppressed dead-code payloads are deterministically sorted and
  do not alter active finding IDs/order.

Refs:

- `codeclone/suppressions.py:extract_suppression_directives`
- `codeclone/suppressions.py:bind_suppressions_to_declarations`
- `codeclone/cache.py:_canonicalize_cache_entry`

## Locked by tests

- `tests/test_suppressions.py::test_extract_suppression_directives_supports_inline_and_leading_forms`
- `tests/test_suppressions.py::test_extract_suppression_directives_ignores_unknown_and_malformed_safely`
- `tests/test_suppressions.py::test_bind_suppressions_applies_only_to_adjacent_declaration_line`
- `tests/test_suppressions.py::test_bind_suppressions_does_not_propagate_class_inline_to_method`
- `tests/test_suppressions.py::test_bind_suppressions_applies_to_method_target`
- `tests/test_suppressions.py::test_build_suppression_index_deduplicates_rules_stably`
- `tests/test_extractor.py::test_dead_code_applies_inline_suppression_per_declaration`
- `tests/test_extractor.py::test_dead_code_suppression_binding_is_scoped_to_target_symbol`
- `tests/test_metrics_modules.py::test_find_unused_applies_inline_dead_code_suppression`
- `tests/test_metrics_modules.py::test_find_suppressed_unused_returns_actionable_suppressed_candidates`
- `tests/test_report.py::test_report_json_dead_code_suppressed_items_are_reported_separately`
- `tests/test_html_report.py::test_html_report_renders_dead_code_split_with_suppressed_layer`

## Non-guarantees

- No file-level/project-level suppressions are provided.
- No generic suppression UI over all finding families is guaranteed in this
  chapter.

## See also

- [16-dead-code-contract.md](16-dead-code-contract.md)
- [08-report.md](08-report.md)
