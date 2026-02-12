# 12. Determinism

## Purpose
Document deterministic behavior and canonicalization controls.

## Public surface
- Sorting and traversal: `codeclone/scanner.py`, `codeclone/_report_serialize.py`, `codeclone/cache.py`
- Canonical hashing: `codeclone/baseline.py`, `codeclone/cache.py`
- Golden detector snapshot policy: `tests/test_detector_golden.py`

## Data model
Deterministic outputs depend on:
- fixed Python tag
- fixed baseline/cache/report schemas
- sorted file traversal
- sorted group keys and item records
- canonical JSON serialization for hashes

## Contracts
- JSON report uses deterministic ordering for files/groups/items.
- TXT report uses deterministic metadata key order and group/item ordering.
- Baseline hash is canonical and independent from non-payload metadata fields.
- Cache signature is canonical and independent from JSON whitespace.

Refs:
- `codeclone/_report_serialize.py:to_json_report`
- `codeclone/_report_serialize.py:to_text_report`
- `codeclone/baseline.py:_compute_payload_sha256`
- `codeclone/cache.py:_sign_data`

## Invariants (MUST)
- `files` list is lexicographically sorted.
- `groups_split` key lists are lexicographically sorted.
- Baseline clone lists are sorted and unique.
- Golden detector test runs only on canonical Python tag from fixture metadata.

Refs:
- `codeclone/_report_serialize.py:_collect_files`
- `codeclone/baseline.py:_require_sorted_unique_ids`
- `tests/test_detector_golden.py::test_detector_output_matches_golden_fixture`

## Failure modes
| Condition | Determinism impact |
| --- | --- |
| Different Python tag | Clone IDs may differ; baseline considered incompatible |
| Unsorted/non-canonical baseline IDs | Baseline rejected as invalid |
| Cache signature mismatch | Cache ignored and recomputed |

## Determinism / canonicalization
Primary canonicalization points:
- `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` for baseline/cache payload hash/signature.
- tuple-based sort keys for report record arrays.

Refs:
- `codeclone/baseline.py:_compute_payload_sha256`
- `codeclone/cache.py:_canonical_json`
- `codeclone/_report_serialize.py:_function_record_sort_key`

## Locked by tests
- `tests/test_report.py::test_report_json_deterministic_group_order`
- `tests/test_report.py::test_report_json_deterministic_with_shuffled_units`
- `tests/test_report.py::test_text_report_deterministic_group_order`
- `tests/test_baseline.py::test_baseline_hash_canonical_determinism`
- `tests/test_cache.py::test_cache_signature_validation_ignores_json_whitespace`

## Non-guarantees
- Determinism is not guaranteed across different `python_tag` values.
