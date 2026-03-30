# 02. Terminology

## Purpose

Define terms exactly as used by code and tests.

## Public surface

- Baseline identifiers and statuses: `codeclone/baseline.py`
- Cache statuses and compact layout: `codeclone/cache.py`
- Report schema and group layouts: `codeclone/report/json_contract.py`

## Data model

- **fingerprint**: function-level CFG fingerprint (`sha1`) + LOC bucket key.
- **block_hash**: ordered sequence of normalized statement hashes in a fixed window.
- **segment_hash**: hash of ordered segment window.
- **segment_sig**: hash of sorted segment window (candidate grouping signature).
- **stable structure facts**: per-function deterministic structure profile fields
  (`entry_guard_*`, `terminal_kind`, `try_finally_profile`,
  `side_effect_order_profile`) reused by report families.
- **cohort structural findings**: report-only structural families derived from
  existing function-clone groups (`clone_guard_exit_divergence`,
  `clone_cohort_drift`).
- **python_tag**: runtime compatibility tag like `cp313`.
- **schema_version**:
    - baseline schema (`meta.schema_version`) for baseline compatibility.
    - cache schema (`v`) for cache compatibility.
    - report schema (`report_schema_version`) for report format compatibility.
- **payload_sha256**: canonical baseline semantic hash.
- **trusted baseline**: baseline loaded + status `ok`.
- **source_kind**: file classification — `production`, `tests`, `fixtures`, `other` —
  determined by scanner path rules. Drives source-scope breakdown and
  hotspot attribution.
- **health score**: weighted blend of seven dimension scores (0–100).
  Dimensions: clones 25%, complexity 20%, cohesion 15%, coupling 10%,
  dead code 10%, dependencies 10%, coverage 10%.
  Grade bands: A ≥90, B ≥75, C ≥60, D ≥40, F <40.
- **design finding**: metric-driven finding (complexity/coupling/cohesion)
  emitted by the canonical report builder when a class or function exceeds
  the report-level design threshold. Thresholds are stored in
  `meta.analysis_thresholds.design_findings`.
- **suggestion**: advisory recommendation card derived from clones, structural
  findings, or metric violations. Advisory only — never gates CI.
- **production_hotspot**: finding group whose items are concentrated in
  production source scope (`source_kind=production`).
- **effective_freshness**: cache-level indicator (`fresh` / `mixed` / `reused`)
  reflecting how much of the analysis was recomputed vs cache-served.
- **directory_hotspot**: derived aggregation in `derived.overview` showing
  which directories concentrate the most findings by category.

Refs:

- `codeclone/grouping.py:build_groups`
- `codeclone/blocks.py:extract_blocks`
- `codeclone/blocks.py:extract_segments`
- `codeclone/baseline.py:current_python_tag`
- `codeclone/baseline.py:Baseline.verify_compatibility`
- `codeclone/scanner.py:classify_source_kind`
- `codeclone/metrics/health.py:compute_health`
- `codeclone/report/json_contract.py:_design_findings_thresholds_payload`
- `codeclone/report/suggestions.py:generate_suggestions`
- `codeclone/report/overview.py:build_directory_hotspots`

## Contracts

- New/known classification is key-based, not item-heuristic-based.
- Baseline trust is status-driven.
- Cache trust is status-driven and independent from baseline trust.
- Design finding universe is determined solely by the canonical report builder;
  MCP and HTML read, never resynthesize.
- Suggestions are advisory and never affect exit code.

Refs:

- `codeclone/report/json_contract.py:build_report_document`
- `codeclone/cli.py:_main_impl`

## Invariants (MUST)

- Function group key format: `fingerprint|loc_bucket`.
- Block group key format: `block_hash`.
- Segment group key format: `segment_hash|qualname` (internal/report-only grouping path).

Refs:

- `codeclone/grouping.py:build_groups`
- `codeclone/grouping.py:build_block_groups`
- `codeclone/grouping.py:build_segment_groups`

## Failure modes

| Condition                              | Result                          |
|----------------------------------------|---------------------------------|
| Baseline generator name != `codeclone` | `generator_mismatch`            |
| Baseline python tag mismatch           | `mismatch_python_version`       |
| Cache signature mismatch               | `integrity_failed` cache status |

Refs:

- `codeclone/baseline.py:Baseline.verify_compatibility`
- `codeclone/cache.py:Cache.load`

## Determinism / canonicalization

- Baseline clone ID lists must be sorted and unique.
- Cache compact arrays are sorted by deterministic tuple keys before write.

Refs:

- `codeclone/baseline.py:_require_sorted_unique_ids`
- `codeclone/cache.py:_encode_wire_file_entry`

## Locked by tests

- `tests/test_baseline.py::test_baseline_id_lists_must_be_sorted_and_unique`
- `tests/test_report.py::test_report_json_group_order_is_deterministic_by_count_then_id`
- `tests/test_cache.py::test_cache_version_mismatch_warns`

## Non-guarantees

- Exact wording of status descriptions in UI is not a schema contract.
