# 07. Cache

## Purpose

Define cache schema `2.6`, integrity verification, stale-entry pruning, and
fail-open behavior.

## Public surface

- Cache object lifecycle: `codeclone/cache/store.py:Cache`
- Cache statuses: `codeclone/cache/versioning.py:CacheStatus`
- Stat signature source: `codeclone/cache/store.py:file_stat_signature`
- Wire encode/decode: `codeclone/cache/_wire_encode.py`,
  `codeclone/cache/_wire_decode.py`
- CLI/runtime integration: `codeclone/surfaces/cli/runtime.py`,
  `codeclone/core/discovery.py`

## Data model

On-disk schema (`v == "2.6"`):

- top-level: `v`, `payload`, `sig`
- `payload` keys: `py`, `fp`, `ap`, `files`, optional `sr`
- `ap` (`analysis_profile`) keys:
  `min_loc`, `min_stmt`, `block_min_loc`, `block_min_stmt`,
  `segment_min_loc`, `segment_min_stmt`, `collect_api_surface`
- `files` stores compact per-file entries with stat signature, extracted units,
  optional metrics sections (including report-only `security_surfaces`),
  referenced names/qualnames, and cached source stats
- `sr` stores optional segment-report projection payload

Refs:

- `codeclone/cache/store.py:Cache.load`
- `codeclone/cache/_wire_encode.py:_encode_wire_file_entry`
- `codeclone/cache/_wire_decode.py:_decode_wire_file_entry`

## Contracts

- Cache is optimization-only; invalid cache never blocks analysis.
- Any cache trust failure triggers warning + empty-cache fallback.
- Compatibility gates:
    - `v == CACHE_VERSION`
    - `payload.py == current_python_tag()`
    - `payload.fp == BASELINE_FINGERPRINT_VERSION`
    - `payload.ap` matches the current analysis profile
    - `sig` matches deterministic hash of canonical payload
- Stale deleted-file entries are pruned on save/update; cache must reflect the
  current worktree, not historical deleted modules.
- Cached entries without valid source stats are treated as cache-miss for
  processing counters and reprocessed.

Refs:

- `codeclone/cache/store.py:Cache.load`
- `codeclone/cache/store.py:Cache._ignore_cache`
- `codeclone/cache/integrity.py:sign_cache_payload`
- `codeclone/core/discovery.py:discover`

## Invariants (MUST)

- Cache save writes canonical JSON and atomically replaces the target file.
- Empty sections are omitted from wire entries.
- Referenced names/qualnames are serialized as sorted unique arrays and omitted when empty.
- Cached public-API symbol payloads preserve declared parameter order.
- Legacy `.cache_secret` is warning-only and never used for trust.

Refs:

- `codeclone/cache/store.py:Cache.save`
- `codeclone/cache/_wire_encode.py:_encode_wire_file_entry`
- `codeclone/cache/versioning.py:LEGACY_CACHE_SECRET_FILENAME`

## Failure modes

| Condition                 | `cache_status`                 |
|---------------------------|--------------------------------|
| File missing              | `missing`                      |
| Too large                 | `too_large`                    |
| Stat/read OSError         | `unreadable`                   |
| JSON decode failure       | `invalid_json`                 |
| Type/schema failure       | `invalid_type`                 |
| Version mismatch          | `version_mismatch`             |
| Python tag mismatch       | `python_tag_mismatch`          |
| Fingerprint mismatch      | `mismatch_fingerprint_version` |
| Analysis profile mismatch | `analysis_profile_mismatch`    |
| Signature mismatch        | `integrity_failed`             |

CLI behavior: cache failures do not change exit code; analysis continues without cache.

Refs:

- `codeclone/cache/versioning.py:CacheStatus`
- `codeclone/surfaces/cli/runtime.py:resolve_cache_status`

## Determinism / canonicalization

- Cache signatures are computed over canonical JSON payload.
- Wire file paths and compact row arrays are sorted before write.
- Optional segment-report projection is additive; invalid/missing projection
  falls back to runtime recomputation.

Refs:

- `codeclone/cache/integrity.py:canonical_json`
- `codeclone/cache/projection.py:wire_filepath_from_runtime`
- `codeclone/cache/_wire_encode.py:_encode_wire_file_entry`

## Locked by tests

- `tests/test_cache.py::test_cache_v13_uses_relpaths_when_root_set`
- `tests/test_cache.py::test_cache_load_analysis_profile_mismatch`
- `tests/test_cache.py::test_cache_signature_validation_ignores_json_whitespace`
- `tests/test_cache.py::test_cache_signature_mismatch_warns`
- `tests/test_cache.py::test_cache_too_large_warns`
- `tests/test_cli_inprocess.py::test_cli_reports_cache_too_large_respects_max_size_flag`
- `tests/test_cli_inprocess.py::test_cli_cache_analysis_profile_compatibility`
- `tests/test_core_branch_coverage.py::test_discover_prunes_deleted_cache_entries`

## Non-guarantees

- Cache file content stability across schema bumps is not guaranteed.
- Cache is tamper-evident only; it is not an authenticated secret store.
