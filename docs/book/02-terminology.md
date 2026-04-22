# 02. Terminology

## Purpose

Define terms exactly as used by code and tests.

## Public surface

- Baseline identifiers and statuses: `codeclone/baseline/*`
- Cache statuses and compact layout: `codeclone/cache/*`
- Report schema and group layouts: `codeclone/report/document/*`

## Data model

- **fingerprint**: function-level CFG fingerprint (`sha1`) plus LOC bucket
- **block_hash**: ordered sequence of normalized statement hashes in a fixed window
- **segment_hash**: hash of an ordered segment window
- **segment_sig**: hash of a sorted segment window used for candidate grouping
- **python_tag**: runtime compatibility tag like `cp313`
- **schema_version**:
    - baseline schema in `meta.schema_version`
    - cache schema in top-level `v`
    - report schema in `report_schema_version`
- **payload_sha256**: canonical baseline semantic hash
- **trusted baseline**: baseline loaded with status `ok`
- **source_kind**: file classification `production | tests | fixtures | other`
- **design finding**: metric-driven finding emitted by the canonical report builder using
  `meta.analysis_thresholds.design_findings`
- **suggestion**: advisory recommendation card derived from findings/metrics; never gates CI
- **directory_hotspot**: derived aggregation showing where findings cluster by category

Refs:

- `codeclone/findings/clones/grouping.py:build_groups`
- `codeclone/blocks/__init__.py`
- `codeclone/baseline/trust.py:current_python_tag`
- `codeclone/baseline/clone_baseline.py:Baseline.verify_compatibility`
- `codeclone/scanner.py:classify_source_kind`
- `codeclone/metrics/health.py:compute_health`
- `codeclone/report/document/_common.py:_design_findings_thresholds_payload`
- `codeclone/report/suggestions.py:generate_suggestions`
- `codeclone/report/overview.py:build_directory_hotspots`

## Contracts

- New/known classification is key-based, not heuristic-based.
- Baseline trust is status-driven.
- Cache trust is status-driven and independent from baseline trust.
- Design finding universe is determined by the canonical report builder; MCP and HTML read it, never resynthesize it.
- Suggestions are advisory and never affect exit code.

Refs:

- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/surfaces/cli/workflow.py:_main_impl`

## Invariants (MUST)

- Function group key format: `fingerprint|loc_bucket`
- Block group key format: `block_hash`
- Segment group key format: `segment_hash|qualname`

Refs:

- `codeclone/findings/clones/grouping.py:build_groups`
- `codeclone/findings/clones/grouping.py:build_block_groups`
- `codeclone/findings/clones/grouping.py:build_segment_groups`

## Failure modes

| Condition                              | Result                          |
|----------------------------------------|---------------------------------|
| Baseline generator name != `codeclone` | `generator_mismatch`            |
| Baseline python tag mismatch           | `mismatch_python_version`       |
| Cache signature mismatch               | `integrity_failed` cache status |

Refs:

- `codeclone/baseline/clone_baseline.py:Baseline.verify_compatibility`
- `codeclone/cache/store.py:Cache.load`

## Determinism / canonicalization

- Baseline clone ID lists must be sorted and unique.
- Cache compact arrays are sorted by deterministic tuple keys before write.

Refs:

- `codeclone/baseline/trust.py:_require_sorted_unique_ids`
- `codeclone/cache/_wire_encode.py:_encode_wire_file_entry`

## Locked by tests

- `tests/test_baseline.py::test_baseline_id_lists_must_be_sorted_and_unique`
- `tests/test_report.py::test_report_json_group_order_is_deterministic_by_count_then_id`
- `tests/test_cache.py::test_cache_version_mismatch_warns`

## Non-guarantees

- Exact wording of status descriptions in UI is not a schema contract.
