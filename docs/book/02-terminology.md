# 02. Terminology

## Purpose
Define terms exactly as used by code and tests.

## Public surface
- Baseline identifiers and statuses: `codeclone/baseline.py`
- Cache statuses and compact layout: `codeclone/cache.py`
- Report schema and group layouts: `codeclone/_report_serialize.py`

## Data model
- **fingerprint**: function-level CFG fingerprint (`sha1`) + LOC bucket key.
- **block_hash**: ordered sequence of normalized statement hashes in a fixed window.
- **segment_hash**: hash of ordered segment window.
- **segment_sig**: hash of sorted segment window (candidate grouping signature).
- **python_tag**: runtime compatibility tag like `cp313`.
- **schema_version**:
  - baseline schema (`meta.schema_version`) for baseline compatibility.
  - cache schema (`v`) for cache compatibility.
  - report schema (`meta.report_schema_version`) for report format compatibility.
- **payload_sha256**: canonical baseline semantic hash.
- **trusted baseline**: baseline loaded + status `ok`.

Refs:
- `codeclone/_report_grouping.py:build_groups`
- `codeclone/blocks.py:extract_blocks`
- `codeclone/blocks.py:extract_segments`
- `codeclone/baseline.py:current_python_tag`
- `codeclone/baseline.py:Baseline.verify_compatibility`

## Contracts
- New/known classification is key-based, not item-heuristic-based.
- Baseline trust is status-driven.
- Cache trust is status-driven and independent from baseline trust.

Refs:
- `codeclone/_report_serialize.py:_split_for`
- `codeclone/cli.py:_main_impl`

## Invariants (MUST)
- Function group key format: `fingerprint|loc_bucket`.
- Block group key format: `block_hash`.
- Segment group key format: `segment_hash|qualname` (internal/report-only grouping path).

Refs:
- `codeclone/_report_grouping.py:build_groups`
- `codeclone/_report_grouping.py:build_block_groups`
- `codeclone/_report_grouping.py:build_segment_groups`

## Failure modes
| Condition | Result |
| --- | --- |
| Baseline generator name != `codeclone` | `generator_mismatch` |
| Baseline python tag mismatch | `mismatch_python_version` |
| Cache signature mismatch | `integrity_failed` cache status |

Refs:
- `codeclone/baseline.py:Baseline.verify_compatibility`
- `codeclone/cache.py:Cache._parse_cache_document`

## Determinism / canonicalization
- Baseline clone ID lists must be sorted and unique.
- Cache compact arrays are sorted by deterministic tuple keys before write.

Refs:
- `codeclone/baseline.py:_require_sorted_unique_ids`
- `codeclone/cache.py:_encode_wire_file_entry`

## Locked by tests
- `tests/test_baseline.py::test_baseline_id_lists_must_be_sorted_and_unique`
- `tests/test_report.py::test_report_json_group_order_is_lexicographic`
- `tests/test_cache.py::test_cache_version_mismatch_warns`

## Non-guarantees
- Exact wording of status descriptions in UI is not a schema contract.
