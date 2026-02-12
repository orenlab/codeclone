# 05. Core Pipeline

## Purpose
Describe the detection pipeline from file discovery to grouped clones.

## Public surface
Pipeline entrypoints:
- Discovery: `codeclone/scanner.py:iter_py_files`
- Per-file processing: `codeclone/cli.py:process_file`
- Extraction: `codeclone/extractor.py:extract_units_from_source`
- Grouping: `codeclone/_report_grouping.py`

## Data model
Stages:
1. Discover Python files (`iter_py_files`, sorted traversal)
2. Load from cache if `stat` signature matches
3. Process changed files:
   - read source
   - AST parse with limits
   - extract units/blocks/segments
4. Build groups:
   - function groups by `fingerprint|loc_bucket`
   - block groups by `block_hash`
   - segment groups by `segment_sig` then `segment_hash|qualname`
5. Report-layer post-processing:
   - merge block windows to maximal regions
   - merge/suppress segment report groups

Refs:
- `codeclone/cli.py:_main_impl`
- `codeclone/extractor.py:extract_units_from_source`
- `codeclone/_report_blocks.py:prepare_block_report_groups`
- `codeclone/_report_segments.py:prepare_segment_report_groups`

## Contracts
- Detection core (`extractor`, `normalize`, `cfg`, `blocks`) computes clone candidates.
- Report-layer transformations do not change function/block grouping keys used for baseline diff.
- Segment groups are report-only and do not participate in baseline diff/gating.

Refs:
- `codeclone/cli.py:_main_impl` (diff uses only function/block groups)
- `codeclone/baseline.py:Baseline.diff`

## Invariants (MUST)
- `Files found = Files analyzed + Cache hits + Files skipped` warning if broken.
- In gating mode, unreadable source IO (`source_read_error`) is a contract failure.
- Parser time/resource protections are applied in POSIX mode via `_parse_limits`.

Refs:
- `codeclone/_cli_summary.py:_print_summary`
- `codeclone/cli.py:_main_impl`
- `codeclone/extractor.py:_parse_limits`

## Failure modes
| Condition | Behavior |
| --- | --- |
| File stat/read/encoding error | File skipped; tracked as failed file; source-read subset tracked separately |
| Source read error in gating mode | Contract error exit 2 |
| Parser timeout | `ParseError` returned through processing failure path |
| Unexpected per-file exception | Captured as `ProcessingResult(error_kind="unexpected_error")` |

## Determinism / canonicalization
- File list is sorted.
- Group sorting in reports is deterministic by key and stable item sort.

Refs:
- `codeclone/scanner.py:iter_py_files`
- `codeclone/_report_serialize.py:_item_sort_key`

## Locked by tests
- `tests/test_scanner_extra.py::test_iter_py_files_deterministic_sorted_order`
- `tests/test_cli_inprocess.py::test_cli_summary_cache_miss_metrics`
- `tests/test_cli_inprocess.py::test_cli_unreadable_source_fails_in_ci_with_contract_error`
- `tests/test_extractor.py::test_parse_limits_triggers_timeout`

## Non-guarantees
- Parallel scheduling order is not guaranteed; only final grouped output determinism is guaranteed.
