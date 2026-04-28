# 17. Suggestions and Clone Typing

## Purpose

Define deterministic clone-type classification and suggestion generation used by
canonical report projections.

## Public surface

- Clone-type classifier: `codeclone/report/suggestions.py:classify_clone_type`
- Suggestion engine: `codeclone/report/suggestions.py:generate_suggestions`
- Pipeline integration: `codeclone/core/pipeline.py:compute_suggestions`
- Report serialization: `codeclone/report/document/builder.py:build_report_document`
- HTML render integration: `codeclone/report/html/assemble.py:build_html_report`

## Data model

Suggestion shape:

- `severity`
- `category`
- `source_kind`
- `title`
- `location`
- `steps`
- `effort`
- `priority`

Clone typing:

- function groups:
    - Type-1: identical `raw_hash`
    - Type-2: identical normalized `fingerprint`
    - Type-3: mixed fingerprints inside same group semantics
    - Type-4: fallback
- block and segment groups: Type-4

Refs:

- `codeclone/models.py:Suggestion`
- `codeclone/report/suggestions.py:classify_clone_type`

## Contracts

- Suggestions are generated only in full metrics mode.
- Suggestions are advisory only and never directly control exit code.
- Suggestions are not a one-to-one mirror of findings; they exist only when they add action structure.
- Low-signal local structural info hints stay in findings and do not emit separate suggestion cards.
- SARIF remains finding-driven and does not consume suggestion cards.
- JSON report stores clone typing at group level under clone groups.

Refs:

- `codeclone/core/pipeline.py:analyze`
- `codeclone/core/pipeline.py:compute_suggestions`
- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/report/suggestions.py:generate_suggestions`

## Invariants (MUST)

- Suggestion priority formula is stable.
- Structural suggestion cards are emitted only for the actionable subset.
- Suggestion output is deterministically sorted.
- Clone type output for identical inputs is deterministic.

Refs:

- `codeclone/report/suggestions.py:_priority`
- `codeclone/report/suggestions.py:generate_suggestions`

## Failure modes

| Condition                              | Behavior                              |
|----------------------------------------|---------------------------------------|
| Metrics mode skipped                   | Suggestions list is empty             |
| No eligible findings                   | Suggestions list is empty             |
| Missing optional fields in group items | Classifier/renderer use safe defaults |

## Determinism / canonicalization

- Classifier uses deterministic set normalization and sorted collections.
- Serializer emits suggestions in deterministic order.

Refs:

- `codeclone/report/suggestions.py:classify_clone_type`
- `codeclone/report/document/builder.py:build_report_document`

## Locked by tests

- `tests/test_report_suggestions.py::test_classify_clone_type_all_modes`
- `tests/test_report_suggestions.py::test_generate_suggestions_covers_clone_metrics_and_dependency_categories`
- `tests/test_report_suggestions.py::test_generate_suggestions_covers_skip_branches_for_optional_rules`
- `tests/test_html_report.py::test_html_report_suggestions_cards_split_facts_assessment_and_action`

## Non-guarantees

- Suggestion wording can evolve without a schema bump.
- Suggestion heuristics may be refined if deterministic ordering and non-gating behavior remain unchanged.
