# 01. Architecture Map

## Purpose
Document the current module boundaries and ownership in the codebase.

## Public surface
Main ownership layers:
- Core detection pipeline: scanner → extractor → cfg/normalize → grouping.
- Contracts/IO: baseline, cache, CLI validation, exit semantics.
- Report model/serialization: JSON/TXT generation and explainability facts.
- Render layer: HTML rendering and template assets.

## Data model
| Layer | Modules | Responsibility |
| --- | --- | --- |
| Contracts | `codeclone/contracts.py`, `codeclone/errors.py` | Shared schema versions, URLs, exit-code enum, typed exceptions |
| Discovery + parsing | `codeclone/scanner.py`, `codeclone/extractor.py` | Enumerate files, parse AST, extract function/block/segment units |
| Structural analysis | `codeclone/cfg.py`, `codeclone/normalize.py`, `codeclone/blockhash.py`, `codeclone/fingerprint.py`, `codeclone/blocks.py` | CFG, normalization, statement hashes, block/segment windows |
| Grouping + report core | `codeclone/_report_grouping.py`, `codeclone/_report_blocks.py`, `codeclone/_report_segments.py`, `codeclone/_report_explain.py` | Build groups, merge windows, suppress segment noise, compute explainability facts |
| Report serialization | `codeclone/_report_serialize.py`, `codeclone/_cli_meta.py` | Canonical JSON/TXT schema + shared report metadata |
| Rendering | `codeclone/html_report.py`, `codeclone/_html_escape.py`, `codeclone/_html_snippets.py`, `codeclone/templates.py` | HTML-only view layer over report model |
| Runtime orchestration | `codeclone/cli.py`, `codeclone/_cli_args.py`, `codeclone/_cli_paths.py`, `codeclone/_cli_summary.py`, `codeclone/ui_messages.py` | CLI UX, status handling, outputs, error category markers |

Refs:
- `codeclone/report.py`
- `codeclone/cli.py:_main_impl`

## Contracts
- Core pipeline does not depend on HTML modules.
- HTML rendering receives already-computed report data/facts.
- Baseline and cache contracts are validated before being trusted.

Refs:
- `codeclone/report.py`
- `codeclone/html_report.py:build_html_report`
- `codeclone/baseline.py:Baseline.load`
- `codeclone/cache.py:Cache.load`

## Invariants (MUST)
- Report serialization is deterministic and schema-versioned.
- UI is render-only and must not recompute detection semantics.
- Status enums are domain-owned in baseline/cache modules.

Refs:
- `codeclone/_report_serialize.py:to_json_report`
- `codeclone/_report_explain.py:build_block_group_facts`
- `codeclone/baseline.py:BaselineStatus`
- `codeclone/cache.py:CacheStatus`

## Failure modes
| Condition | Layer |
| --- | --- |
| Invalid CLI args / invalid output path | Runtime orchestration (`_cli_args`, `_cli_paths`) |
| Baseline schema/integrity mismatch | Baseline contract layer |
| Cache corruption/version mismatch | Cache contract layer (fail-open) |
| HTML snippet read failure | Render layer fallback snippet |

## Determinism / canonicalization
- File iteration and group key ordering are explicit sorts.
- Report serializer uses fixed record layouts and sorted keys.

Refs:
- `codeclone/scanner.py:iter_py_files`
- `codeclone/_report_serialize.py:GROUP_ITEM_LAYOUT`

## Locked by tests
- `tests/test_report.py::test_report_json_compact_v11_contract`
- `tests/test_html_report.py::test_html_report_uses_core_block_group_facts`
- `tests/test_cache.py::test_cache_v12_uses_relpaths_when_root_set`
- `tests/test_cli_unit.py::test_argument_parser_contract_error_marker_for_invalid_args`

## Non-guarantees
- Internal module split may change in v1.x if public contracts are preserved.
- Import tree acyclicity is a policy goal, not currently enforced by tooling.
