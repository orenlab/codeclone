# 08. Report

## Purpose
Define report schema v1.1 and shared metadata contract across JSON/TXT/HTML.

## Public surface
- JSON serializer: `codeclone/_report_serialize.py:to_json_report`
- TXT serializer: `codeclone/_report_serialize.py:to_text_report`
- Shared metadata builder: `codeclone/_cli_meta.py:_build_report_meta`
- HTML renderer: `codeclone/html_report.py:build_html_report`

## Data model
JSON v1.1 top-level fields:
- `meta`
- `files`
- `groups`
- `groups_split`
- `group_item_layout`
- optional `facts`

`group_item_layout` is explicit positional schema for compact arrays.

Refs:
- `codeclone/_report_serialize.py:GROUP_ITEM_LAYOUT`
- `codeclone/contracts.py:REPORT_SCHEMA_VERSION`

## Contracts
Shared `meta` contract is produced once in CLI and consumed by all formats.
Key fields include:
- runtime: `codeclone_version`, `python_version`, `python_tag`, `report_schema_version`
- deterministic aggregates: `groups_counts.{functions|blocks|segments}.{total,new,known}`
- baseline provenance: `baseline_*`, including `baseline_payload_sha256` and verification flag
- cache provenance: `cache_path`, `cache_used`, `cache_status`, `cache_schema_version`
- IO transparency: `files_skipped_source_io`

Refs:
- `codeclone/_cli_meta.py:ReportMeta`
- `codeclone/_cli_meta.py:_build_report_meta`

NEW/KNOWN split contract:
- Trusted baseline (`baseline_loaded=true` and `baseline_status=ok`):
  - `new` from `new_*_group_keys`
  - `known` is remaining keys
- Untrusted baseline: all groups are NEW, KNOWN is empty

Refs:
- `codeclone/_report_serialize.py:_baseline_is_trusted`
- `codeclone/_report_serialize.py:to_json_report`
- `codeclone/_report_serialize.py:to_text_report`

## Invariants (MUST)
- `groups_split` is key-index only; clone payload stays in `groups`.
- `groups_split[new] ∩ groups_split[known] = ∅` per section.
- `groups_split[new] ∪ groups_split[known] = groups.keys()` per section.
- Facts are core-owned (`build_block_group_facts`) and renderers only display them.

Refs:
- `codeclone/_report_serialize.py:to_json_report`
- `codeclone/_report_explain.py:build_block_group_facts`

## Failure modes
| Condition | Behavior |
| --- | --- |
| Missing meta fields at render time | TXT/HTML render placeholders `(none)` or empty values |
| Untrusted baseline | JSON/TXT classify all groups as NEW; HTML shows untrusted note |
| Missing source snippets | HTML shows safe fallback snippet |

Refs:
- `codeclone/_report_serialize.py:_format_meta_text_value`
- `codeclone/html_report.py:build_html_report`
- `codeclone/_html_snippets.py:_render_code_block`

## Determinism / canonicalization
- `files` list is sorted and unique by collection strategy.
- Group keys are serialized in sorted order.
- Items are encoded and sorted by deterministic tuple keys.

Refs:
- `codeclone/_report_serialize.py:_collect_files`
- `codeclone/_report_serialize.py:_function_record_sort_key`
- `codeclone/_report_serialize.py:_block_record_sort_key`

## Locked by tests
- `tests/test_report.py::test_report_json_compact_v11_contract`
- `tests/test_report.py::test_report_json_groups_split_trusted_baseline`
- `tests/test_report.py::test_report_json_groups_split_untrusted_baseline`
- `tests/test_report.py::test_to_text_report_trusted_baseline_split_sections`
- `tests/test_report.py::test_to_text_report_untrusted_baseline_known_sections_empty`

## Non-guarantees
- Optional `facts` payload may expand in v1.x without changing clone group semantics.
- HTML visual grouping controls are not part of JSON schema contract.
