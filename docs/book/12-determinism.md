# 12. Determinism

## Purpose

Document deterministic behavior and canonicalization controls.

## Public surface

- Sorted file traversal: `codeclone/scanner.py`
- Canonical report construction: `codeclone/report/document/*`
- Deterministic text projection: `codeclone/report/renderers/text.py`
- Baseline hashing: `codeclone/baseline/trust.py`
- Cache signing: `codeclone/cache/integrity.py`

## Data model

Deterministic outputs depend on:

- fixed Python tag
- fixed baseline/cache/report schemas
- sorted file traversal
- sorted group keys and item records
- canonical JSON serialization for hashes/signatures

## Contracts

- Canonical JSON report uses deterministic ordering for files, groups, items, and summaries.
- Text/Markdown/SARIF projections are deterministic views over the canonical report.
- Baseline hash is canonical and independent from non-payload metadata fields.
- Cache signature is canonical and independent from JSON whitespace.

Refs:

- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/report/renderers/text.py:render_text_report_document`
- `codeclone/baseline/trust.py:_compute_payload_sha256`
- `codeclone/cache/integrity.py:sign_cache_payload`

## Invariants (MUST)

- `inventory.file_registry.items` is lexicographically sorted.
- finding groups/items and derived hotlists are deterministically ordered.
- baseline clone lists are sorted and unique.
- golden detector fixtures run only on the canonical Python tag from fixture metadata.

Refs:

- `codeclone/report/document/inventory.py:_build_inventory_payload`
- `codeclone/baseline/trust.py:_require_sorted_unique_ids`
- `tests/test_detector_golden.py::test_detector_output_matches_golden_fixture`

## Failure modes

| Condition                           | Determinism impact                                  |
|-------------------------------------|-----------------------------------------------------|
| Different Python tag                | Clone IDs may differ; baseline becomes incompatible |
| Unsorted/non-canonical baseline IDs | Baseline rejected as invalid                        |
| Cache signature mismatch            | Cache ignored and recomputed                        |
| Different cache provenance state    | `meta.cache_*` differs by design                    |

## Determinism / canonicalization

Primary canonicalization points:

- canonical JSON with sorted keys and compact separators for baseline/cache hashing
- stable tuple-based sort keys for report arrays and hotlists

Refs:

- `codeclone/baseline/trust.py:_compute_payload_sha256`
- `codeclone/cache/integrity.py:canonical_json`
- `codeclone/report/document/integrity.py:_build_integrity_payload`

## Locked by tests

- `tests/test_report.py::test_report_json_deterministic_group_order`
- `tests/test_report.py::test_report_json_deterministic_with_shuffled_units`
- `tests/test_report.py::test_text_report_deterministic_group_order`
- `tests/test_baseline.py::test_baseline_hash_canonical_determinism`
- `tests/test_cache.py::test_cache_signature_validation_ignores_json_whitespace`

## Non-guarantees

- Determinism is not guaranteed across different `python_tag` values.
- Byte-identical reports are not guaranteed across different cache provenance states.
