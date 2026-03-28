# 08. Report

## Purpose

Define report contracts in `2.0.0b3`: canonical JSON (`report_schema_version=2.1`)
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

Derived projection layer:

- `derived.suggestions[*]` — actionable projection cards keyed back to canonical
  findings via `finding_id`
- `derived.overview` — summary-only overview facts:
    - `families`
    - `top_risks`
    - `source_scope_breakdown`
    - `health_snapshot`
- `derived.hotlists` — deterministic lists of canonical finding IDs:
    - `most_actionable_ids`
    - `highest_spread_ids`
    - `production_hotspot_ids`
    - `test_fixture_hotspot_ids`

Finding families:

- `findings.groups.clones.{functions,blocks,segments}`
- `findings.groups.structural.groups`
- `findings.groups.dead_code.groups`
- `findings.groups.design.groups`
- `findings.summary.suppressed.dead_code` (suppressed counter, non-active findings)

Structural finding kinds currently emitted by core/report pipeline:

- `duplicated_branches`
- `clone_guard_exit_divergence`
- `clone_cohort_drift`

Per-group common axes (family-specific fields may extend):

- identity: `id`, `family`, `category`, `kind`
- assessment: `severity`, `confidence`, `priority`
- scope: `source_scope` (`dominant_kind`, `breakdown`, `impact_scope`)
- spread: `spread.files`, `spread.functions`
- evidence: `items`, `facts` (+ optional `display_facts`)

## Contracts

- JSON is source of truth for report semantics.
- Markdown and SARIF are deterministic projections from the same report document.
- MCP summary/finding/hotlist/report-section queries are deterministic views over
  the same canonical report document.
- SARIF is an IDE/code-scanning-oriented projection:
    - repo-relative result paths are anchored via `%SRCROOT%`
    - referenced files are listed under `run.artifacts`
    - clone results carry `baselineState` when clone novelty is known
- Derived layer (`suggestions`, `overview`, `hotlists`) does not replace canonical
  findings/metrics.
- HTML overview cards are materialized from canonical findings plus
  `derived.overview` + `derived.hotlists`; pre-expanded overview card payloads are
  not part of the report contract.
- Overview hotspot/source-breakdown sections must resolve from canonical report
  data or deterministic derived IDs; HTML must not silently substitute stale
  placeholders such as `n/a` or empty-state cards when canonical data exists.
- `analysis_started_at_utc` and `report_generated_at_utc` are carried in
  `meta.runtime`; renderers/projections may use them for provenance but must not
  reinterpret them as semantic analysis data.
- Canonical `meta.scan_root` is normalized to `"."`; absolute runtime paths are
  exposed under `meta.runtime.*_absolute`.
- `clone_type` and `novelty` are group-level properties inside clone groups.
- Cohort-drift structural families are report-only and must not affect baseline diff
  or CI gating decisions.
- Dead-code suppressed candidates are carried only under metrics
  (`metrics.families.dead_code.suppressed_items`) and never promoted to
  active `findings.groups.dead_code`.

## Invariants (MUST)

- Stable ordering for groups/items/suggestions/hotlists.
- Stable ordering for SARIF rules, artifacts, and results.
- `derived.suggestions[*].finding_id` references existing canonical finding IDs.
- `derived.hotlists.*_ids` reference existing canonical finding IDs.
- SARIF `artifacts[*]` and `locations[*].artifactLocation.index` stay aligned.
- `integrity.digest` is computed from canonical sections only (derived excluded).
- `source_scope.impact_scope` is explicit and deterministic (`runtime`,
  `non_runtime`, `mixed`).

## Failure modes

| Condition                       | Behavior                                       |
|---------------------------------|------------------------------------------------|
| Missing optional UI/meta fields | Renderer falls back to empty/`(none)` display  |
| Untrusted baseline              | Clone novelty resolves to `new` for all groups |
| Missing snippet source in HTML  | Safe fallback snippet block                    |

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
- `tests/test_report.py::test_json_includes_clone_guard_exit_divergence_structural_group`
- `tests/test_report.py::test_json_includes_clone_cohort_drift_structural_group`
- `tests/test_report.py::test_report_json_dead_code_suppressed_items_are_reported_separately`

## Non-guarantees

- Human-readable wording in `derived` or HTML may evolve without schema bump.
- CSS/layout changes are not part of JSON contract.

## See also

- [07-cache.md](07-cache.md)
- [09-cli.md](09-cli.md)
- [10-html-render.md](10-html-render.md)
- [20-mcp-interface.md](20-mcp-interface.md)
- [17-suggestions-and-clone-typing.md](17-suggestions-and-clone-typing.md)
- [../sarif.md](../sarif.md)
- [../examples/report.md](../examples/report.md)
