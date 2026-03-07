# 08. Report

## Purpose

Define report schema v2.0 and shared metadata contract across JSON/TXT/HTML.

## Public surface

- JSON/TXT serializer: `codeclone/report/serialize.py`
- Shared metadata builder: `codeclone/_cli_meta.py:_build_report_meta`
- HTML renderer: `codeclone/html_report.py:build_html_report`

## Data model

JSON v2.0 top-level fields:

- `report_schema_version`
- `meta`
- `files`
- `groups`
- `groups_split`
- `group_item_layout`
- `clones`
- `clone_types`
- optional `facts`
- optional `metrics`
- optional `suggestions`

`group_item_layout` is explicit positional schema for compact arrays.

Refs:

- `codeclone/report/serialize.py:GROUP_ITEM_LAYOUT`
- `codeclone/contracts.py:REPORT_SCHEMA_VERSION`

## Contracts

Shared `meta` contract is produced once in CLI and consumed by all formats.
Key fields include:

- runtime: `codeclone_version`, `python_version`, `python_tag`,
  `report_schema_version`
- scan identity: `project_name`, `scan_root`
- baseline provenance: `baseline_*`, including payload verification fields
- metrics-baseline provenance: `metrics_baseline_*`
- cache provenance: `cache_path`, `cache_used`, `cache_status`,
  `cache_schema_version`
- run transparency: `files_skipped_source_io`, `analysis_mode`,
  `metrics_computed`, `health_score`, `health_grade`

Refs:

- `codeclone/_cli_meta.py:ReportMeta`
- `codeclone/_cli_meta.py:_build_report_meta`

NEW/KNOWN split contract:

- Trusted baseline (`baseline_loaded=true` and `baseline_status=ok`):
  `new` comes from `new_*_group_keys`, `known` is the remaining keys.
- Untrusted baseline: all groups are NEW, KNOWN is empty.

Refs:

- `codeclone/report/serialize.py:_baseline_is_trusted`
- `codeclone/report/serialize.py:to_json_report`
- `codeclone/report/serialize.py:to_text_report`

## Invariants (MUST)

- `groups_split` is key-index only; clone payload stays in `groups`.
- For each section:
  `new ∩ known = ∅` and `new ∪ known = groups.keys()`.
- Facts are core-owned and renderers only display them.

Refs:

- `codeclone/report/serialize.py:to_json_report`
- `codeclone/report/explain.py:build_block_group_facts`

## Failure modes

| Condition                          | Behavior                                                       |
|------------------------------------|----------------------------------------------------------------|
| Missing meta fields at render time | TXT/HTML render placeholders `(none)` or empty values          |
| Untrusted baseline                 | JSON/TXT classify all groups as NEW; HTML shows untrusted note |
| Missing source snippets            | HTML shows safe fallback snippet                               |

Refs:

- `codeclone/report/serialize.py:format_meta_text_value`
- `codeclone/html_report.py:build_html_report`
- `codeclone/_html_snippets.py:_render_code_block`

## Determinism / canonicalization

- `files` list is sorted and unique by collection strategy.
- Group keys are serialized in sorted order.
- Items are encoded and sorted by deterministic tuple keys.
- `meta.cache_*` fields are deterministic for fixed run state, but may differ
  between cold/warm runs by design.

Refs:

- `codeclone/report/serialize.py:_collect_files`
- `codeclone/report/serialize.py:_function_record_sort_key`
- `codeclone/report/serialize.py:_block_record_sort_key`

## Locked by tests

- `tests/test_report.py::test_report_json_compact_v20_contract`
- `tests/test_report.py::test_report_json_groups_split_trusted_baseline`
- `tests/test_report.py::test_report_json_groups_split_untrusted_baseline`
- `tests/test_report.py::test_to_text_report_trusted_baseline_split_sections`
- `tests/test_report.py::test_to_text_report_untrusted_baseline_known_sections_empty`

## Non-guarantees

- Optional `facts`/`metrics`/`suggestions` payload sections may expand in v2.x
  without changing clone-group semantics.
- HTML visual controls are not part of JSON schema contract.
- Reports from different cache provenance states (for example `missing` vs
  `ok`) are not byte-identical because `meta.cache_*` is contract data.

## See also

- [10-html-render.md](10-html-render.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
- [17-suggestions-and-clone-typing.md](17-suggestions-and-clone-typing.md)
