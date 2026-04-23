# 08. Report

## Purpose

Define the canonical report contract in `2.0.0b6`: report schema `2.9` plus
deterministic text/Markdown/SARIF/HTML projections.

## Public surface

- Canonical report builder: `codeclone/report/document/builder.py:build_report_document`
- Canonical inventory/integrity helpers:
  `codeclone/report/document/inventory.py`,
  `codeclone/report/document/integrity.py`
- Text renderer: `codeclone/report/renderers/text.py:render_text_report_document`
- Markdown renderer:
  `codeclone/report/renderers/markdown.py:render_markdown_report_document`
- SARIF renderer:
  `codeclone/report/renderers/sarif.py:render_sarif_report_document`
- HTML renderer: `codeclone/report/html/assemble.py:build_html_report`
- Shared CLI report meta:
  `codeclone/surfaces/cli/report_meta.py:_build_report_meta`

## Data model

Canonical top-level sections:

- `report_schema_version`
- `meta`
- `inventory`
- `findings`
- `metrics`
- `derived`
- `integrity`

Canonical section roles:

- `meta`, `inventory`, `findings`, `metrics` are canonical truth
- `derived` is a deterministic projection layer
- `integrity` carries canonicalization metadata and digest

Current canonical report-only metric families include:

- `health`
- `dead_code`
- `dependencies`
- `coverage_adoption`
- `api_surface`
- `coverage_join`
- `overloaded_modules`

Dependency depth facts in the canonical report now include:

- `avg_depth`
- `p95_depth`
- `max_depth`

These describe the internal module dependency graph. They are report facts, not
user-facing config knobs.

Current finding families include:

- `findings.groups.clones.{functions,blocks,segments}`
- optional `findings.groups.clones.suppressed.*`
- `findings.groups.structural.groups`
- `findings.groups.dead_code.groups`
- `findings.groups.design.groups`

Refs:

- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/report/document/_common.py:_design_findings_thresholds_payload`
- `codeclone/report/document/_findings_groups.py:_build_clone_groups`
- `codeclone/report/document/_findings_groups.py:_build_structural_groups`

## Contracts

- JSON is the source of truth for report semantics.
- Markdown, text, SARIF, HTML, and MCP projections must read canonical report facts rather than recompute them.
- `derived` does not replace canonical findings/metrics.
- Design findings are built once in the canonical report using
  `meta.analysis_thresholds.design_findings`; consumers must not synthesize them post-hoc.
- Coverage Join is canonical current-run truth for that run, but not baseline truth.
- Clone groups excluded by project policy are carried only under suppressed clone buckets and do not affect active
  findings, health, clone gating, or suggestions.

Refs:

- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/report/derived.py:_health_snapshot`
- `codeclone/report/overview.py:materialize_report_overview`
- `codeclone/report/suggestions.py:generate_suggestions`

## Invariants (MUST)

- Stable ordering for groups, items, suggestions, and hotlists.
- `derived.suggestions[*].finding_id` references existing canonical finding IDs.
- `derived.hotlists.*_ids` reference existing canonical finding IDs.
- SARIF artifacts, rules, and locations stay index-aligned.
- `integrity.digest` is computed from canonical sections only; `derived` is excluded.

Refs:

- `codeclone/report/document/integrity.py:_build_integrity_payload`
- `codeclone/report/document/inventory.py:_build_inventory_payload`
- `codeclone/report/renderers/sarif.py:render_sarif_report_document`

## Failure modes

| Condition                       | Behavior                                               |
|---------------------------------|--------------------------------------------------------|
| Missing optional UI/meta fields | Renderer falls back to empty or `(none)`-style display |
| Untrusted baseline              | Clone novelty resolves as current-run only             |
| Missing source snippet in HTML  | Safe fallback snippet block                            |

## Determinism / canonicalization

- Canonical payload is serialized with sorted keys for digest computation.
- Inventory file registry is normalized to relative paths.
- Structural findings are normalized, deduplicated, and sorted before serialization.

Refs:

- `codeclone/report/document/integrity.py:_build_integrity_payload`
- `codeclone/report/document/inventory.py:_build_inventory_payload`
- `codeclone/findings/structural/detectors.py:normalize_structural_findings`

## Locked by tests

- `tests/test_report.py::test_report_json_compact_v21_contract`
- `tests/test_report.py::test_report_json_integrity_matches_canonical_sections`
- `tests/test_report.py::test_report_json_integrity_ignores_derived_changes`
- `tests/test_report_contract_coverage.py::test_report_document_rich_invariants_and_renderers`
- `tests/test_report_contract_coverage.py::test_markdown_and_sarif_reuse_prebuilt_report_document`
- `tests/test_report_branch_invariants.py::test_overview_and_sarif_branch_invariants`

## Non-guarantees

- Human-facing wording in `derived` or HTML may evolve without a schema bump.
- CSS/layout changes are not part of the canonical report contract.
