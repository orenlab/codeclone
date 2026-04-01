# 17. Suggestions and Clone Typing

## Purpose

Define deterministic clone-type classification and suggestion generation
contracts used by canonical report projections (`JSON` / `TXT` / `Markdown` /
`HTML`).

## Public surface

- Clone-type classifier: `codeclone/report/suggestions.py:classify_clone_type`
- Suggestion engine: `codeclone/report/suggestions.py:generate_suggestions`
- Pipeline integration: `codeclone/pipeline.py:compute_suggestions`
- Report serialization: `codeclone/report/json_contract.py:build_report_document`
- HTML render integration: `codeclone/html_report.py:build_html_report`

## Data model

Suggestion shape:

- `severity`: `critical|warning|info`
- `category`:
  `clone|structural|complexity|coupling|cohesion|dead_code|dependency`
- `source_kind`: source classification of the primary location
  (`production` / `tests` / `fixtures` / `other`)
- `title`, `location`, `steps`, `effort`, `priority`

Clone typing:

- function groups:
    - Type-1: identical `raw_hash`
    - Type-2: identical normalized `fingerprint`
    - Type-3: mixed fingerprints (same group semantics)
    - Type-4: fallback
- block/segment groups: Type-4

Refs:

- `codeclone/models.py:Suggestion`
- `codeclone/report/suggestions.py:classify_clone_type`

## Contracts

- Suggestions are generated only in full metrics mode
  (`skip_metrics=false`).
- Suggestions are advisory only and never directly control exit code.
- SARIF projection is finding-driven and does not consume suggestion cards.
- JSON report stores clone typing at group level:
    - `findings.groups.clones.<kind>[*].clone_type`
- Suggestion location is deterministic: first item by stable path/line sort.

Refs:

- `codeclone/pipeline.py:analyze`
- `codeclone/pipeline.py:gate`
- `codeclone/report/json_contract.py:build_report_document`
- `codeclone/report/suggestions.py:generate_suggestions`

## Invariants (MUST)

- Suggestion priority formula is stable:
  `severity_weight / effort_weight`.
- Suggestion output is sorted by:
  `(-priority, severity, category, source_kind, location, title, subject_key)`.
- Derived suggestion serialization in report JSON applies deterministic ordering by
  `(-priority, severity_rank, title, finding_id)`.
- Clone type output for a given group is deterministic for identical inputs.

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

- Classifier uses deterministic set normalization + sorted collections.
- Serializer emits suggestions in generator-provided deterministic order.

Refs:

- `codeclone/report/suggestions.py:classify_clone_type`
- `codeclone/report/suggestions.py:generate_suggestions`
- `codeclone/report/json_contract.py:build_report_document`

## Locked by tests

- `tests/test_report_suggestions.py::test_classify_clone_type_all_modes`
- `tests/test_report_suggestions.py::test_generate_suggestions_covers_clone_metrics_and_dependency_categories`
- `tests/test_report_suggestions.py::test_generate_suggestions_covers_skip_branches_for_optional_rules`
- `tests/test_html_report.py::test_html_report_suggestions_cards_split_facts_assessment_and_action`

## Non-guarantees

- Suggestion wording can evolve without schema bump.
- Suggestion heuristics may be refined if deterministic ordering and
  non-gating behavior remain unchanged.

## See also

- [05-core-pipeline.md](05-core-pipeline.md)
- [08-report.md](08-report.md)
- [10-html-render.md](10-html-render.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
