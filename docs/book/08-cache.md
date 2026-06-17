<!-- doc-scope: CACHE CONTRACT (schema v2.10).
     owns: cache schema, profile compatibility, fail-open behavior, size guards.
     does-not-own: baseline (→ 07), pipeline (→ 03). -->

# 08. Cache

## Purpose

Define cache schema `2.10`, integrity verification, stale-entry pruning, and
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

On-disk schema (`v == "2.10"`):

- top-level: `v`, `payload`, `sig`
- `payload` keys: `py`, `fp`, `ap`, `files`, optional `sr`
- `ap` (`analysis_profile`) keys:
  `min_loc`, `min_stmt`, `block_min_loc`, `block_min_stmt`,
  `segment_min_loc`, `segment_min_stmt`, `collect_api_surface`
- `files` stores compact per-file entries with stat signature, extracted units,
  optional metrics sections (including runtime reachability evidence and
  report-only `security_surfaces`),
  referenced names/qualnames, cached source stats, and optional
  **`function_relationship_facts`**
- `sr` stores optional segment-report projection payload

### `function_relationship_facts` (per-file cache section)

Cached under the canonical key `function_relationship_facts` in the typed entry;
wire compact key **`fr`**. Each file may store zero or more fact rows keyed by
`source_qualname`, each with a sorted list of relationship records:

| Field               | Meaning                                                |
|---------------------|--------------------------------------------------------|
| `relation_kind`     | Deterministic relationship classifier from module walk |
| `resolution_status` | Resolved vs deferred boundary for the target           |
| `origin_lane`       | Which analysis lane produced the edge                  |
| `target_qualname`   | Callee / related symbol qualname                       |
| `line`              | Source line of the relationship site                   |
| `expression`        | Normalized expression text (bounded)                   |
| `resolution_rule`   | Rule id explaining how the target was resolved         |

Facts are derived during unit extraction (`codeclone/analysis/units.py`) and
persisted on cache save when present. On cache hit, discovery rehydrates them
into the processing pipeline (`codeclone/core/discovery.py`) so warm runs preserve
the same function-relationship evidence as cold runs without recomputing AST
facts. Empty sections are omitted from wire entries.

Refs:

- `codeclone/cache/store.py:Cache.load`
- `codeclone/cache/_wire_encode.py:_encode_function_relationship_facts`
- `codeclone/cache/_wire_decode.py:_decode_optional_wire_function_relationship_facts`
- `codeclone/cache/entries.py:_function_relationship_facts_dict_from_model`

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
- Cached runtime reachability facts are required for cold/warm dead-code
  equivalence across supported framework registration patterns.
- Cached `function_relationship_facts` round-trip deterministically through wire
  encode/decode and preserve relationship ordering within each source qualname.
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
- `codeclone/cache/store.py:resolve_cache_status`

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
- `tests/test_cache.py::test_cache_roundtrip_preserves_function_relationship_facts`
- `tests/test_cli_inprocess.py::test_cli_reports_cache_too_large_respects_max_size_flag`
- `tests/test_cli_inprocess.py::test_cli_cache_analysis_profile_compatibility`
- `tests/test_core_branch_coverage.py::test_discover_prunes_deleted_cache_entries`

## Non-guarantees

- Cache file content stability across schema bumps is not guaranteed.
- Cache is tamper-evident only; it is not an authenticated secret store.
