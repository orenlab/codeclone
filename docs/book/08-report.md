# 08. Report

## Purpose

Define report contracts in `2.0.0b1`: canonical JSON (`report_schema_version=2.1`)
plus deterministic TXT/Markdown/SARIF projections.

## Public surface

- Canonical report builder: `codeclone/report/json_contract.py:build_report_document`
- JSON/TXT renderers: `codeclone/report/serialize.py`
- Markdown renderer: `codeclone/report/markdown.py`
- SARIF renderer: `codeclone/report/sarif.py`
- HTML renderer: `codeclone/html_report.py:build_html_report`
- Shared metadata source: `codeclone/_cli_meta.py:_build_report_meta`

## Data model

JSON report top-level (v2.1):

- `report_schema_version`
- `meta`
- `inventory`
- `findings`
- `metrics`
- `derived`
- `integrity`

Canonical vs non-canonical split:

- Canonical: `report_schema_version`, `meta`, `inventory`, `findings`, `metrics`
- Non-canonical projection layer: `derived`
- Integrity metadata: `integrity` (`canonicalization` + `digest`)

Finding families:

- `findings.groups.clones.{functions,blocks,segments}`
- `findings.groups.structural.groups`
- `findings.groups.dead_code.groups`
- `findings.groups.design.groups`

Per-group common axes (family-specific fields may extend):

- identity: `id`, `family`, `category`, `kind`
- assessment: `severity`, `confidence`, `priority`
- scope: `source_scope` (`dominant_kind`, `breakdown`, `impact_scope`)
- spread: `spread.files`, `spread.functions`
- evidence: `items`, `facts` (+ optional `display_facts`)

## Contracts

- JSON is source of truth for report semantics.
- Markdown and SARIF are deterministic projections from the same report document.
- Derived layer (`suggestions`, `overview`, `hotlists`) does not replace canonical
  findings/metrics.
- `report_generated_at_utc` is carried in `meta.runtime` and reused by UI/renderers.
- `clone_type` and `novelty` are group-level properties inside clone groups.

## Invariants (MUST)

- Stable ordering for groups/items/suggestions/hotlists.
- `derived[*].finding_id` references existing canonical finding IDs.
- `integrity.digest` is computed from canonical sections only (derived excluded).
- `source_scope.impact_scope` is explicit and deterministic (`runtime`,
  `non_runtime`, `mixed`).

## Failure modes

| Condition                         | Behavior |
|-----------------------------------|----------|
| Missing optional UI/meta fields   | Renderer falls back to empty/`(none)` display |
| Untrusted baseline                | Clone novelty resolves to `new` for all groups |
| Missing snippet source in HTML    | Safe fallback snippet block |

## Determinism / canonicalization

- Canonical payload is serialized with sorted keys for digest computation.
- Inventory file registry is normalized to relative paths.
- Structural findings are normalized, deduplicated, and sorted before serialization.

Refs:

- `codeclone/report/json_contract.py:_build_integrity_payload`
- `codeclone/report/json_contract.py:_build_inventory_payload`
- `codeclone/structural_findings.py:normalize_structural_findings`

## Locked by tests

- `tests/test_report.py::test_report_json_compact_v21_contract`
- `tests/test_report.py::test_report_json_integrity_matches_canonical_sections`
- `tests/test_report.py::test_report_json_integrity_ignores_derived_changes`
- `tests/test_report_contract_coverage.py::test_report_document_rich_invariants_and_renderers`
- `tests/test_report_contract_coverage.py::test_markdown_and_sarif_reuse_prebuilt_report_document`
- `tests/test_report_branch_invariants.py::test_overview_and_sarif_branch_invariants`

## Non-guarantees

- Human-readable wording in `derived` or HTML may evolve without schema bump.
- CSS/layout changes are not part of JSON contract.

## See also

- [07-cache.md](07-cache.md)
- [09-cli.md](09-cli.md)
- [10-html-render.md](10-html-render.md)
- [17-suggestions-and-clone-typing.md](17-suggestions-and-clone-typing.md)
