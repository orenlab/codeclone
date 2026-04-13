# 07. Cache

## Purpose

Define cache schema v2.4, integrity verification, and fail-open behavior.

## Public surface

- Cache object lifecycle: `codeclone/cache.py:Cache`
- Cache statuses: `codeclone/cache.py:CacheStatus`
- Stat signature source: `codeclone/cache.py:file_stat_signature`
- CLI cache integration: `codeclone/cli.py:_main_impl`

## Data model

On-disk schema (`v == "2.4"`):

- Top-level: `v`, `payload`, `sig`
- `payload` keys: `py`, `fp`, `ap`, `files`, optional `sr`
- `ap` (`analysis_profile`) keys:
    - `min_loc`, `min_stmt`
    - `block_min_loc`, `block_min_stmt`
    - `segment_min_loc`, `segment_min_stmt`
- `files` map stores compact per-file entries:
    - `st`: `[mtime_ns, size]`
    - `ss`: `[lines, functions, methods, classes]` (source stats snapshot)
    - `u` (function units): compact row layout with structural facts:
      `[qualname,start,end,loc,stmt_count,fingerprint,loc_bucket,cc,nesting,risk,raw_hash,entry_guard_count,entry_guard_terminal_profile,entry_guard_has_side_effect_before,terminal_kind,try_finally_profile,side_effect_order_profile]`
    - optional analysis sections (`b`/`s` and metrics-related sections)
    - `rn`: referenced local names (non-test files only)
    - `rq`: referenced canonical qualnames (non-test files only)
- file keys are wire relpaths when `root` is configured
- optional `sr` (`segment report projection`) stores precomputed segment-report
  merge/suppression output:
    - `d`: digest of raw segment groups
    - `s`: suppressed segment groups count
    - `g`: grouped merged segment items (wire rows)
- per-file `dc` (`dead_candidates`) rows do not repeat filepath; path is implied by
  the containing file entry

Refs:

- `codeclone/cache.py:Cache.load`
- `codeclone/cache.py:_encode_wire_file_entry`
- `codeclone/cache.py:_decode_wire_file_entry`

## Contracts

- Cache is optimization-only; invalid cache never blocks analysis.
- Any cache trust failure triggers warning + empty cache fallback.
- Cached file entry without valid `ss` (`source_stats`) is treated as cache-miss for
  processing counters and reprocessed.
- Cache compatibility gates:
    - version `v == CACHE_VERSION`
    - `payload.py == current_python_tag()`
    - `payload.fp == BASELINE_FINGERPRINT_VERSION`
    - `payload.ap` matches the current six-threshold analysis profile
      (`min_loc`, `min_stmt`, `block_min_loc`, `block_min_stmt`,
      `segment_min_loc`, `segment_min_stmt`)
    - `sig` equals deterministic hash of canonical payload
- Cache schema must also be bumped when cached analysis semantics change in a
  way that could leave syntactically valid but semantically stale per-file
  entries accepted by runtime compatibility checks.

Refs:

- `codeclone/cache.py:Cache.load`
- `codeclone/cache.py:Cache._ignore_cache`
- `codeclone/cache.py:Cache._sign_data`

## Invariants (MUST)

- Cache save writes canonical JSON and atomically replaces target file.
- Empty sections (`u`, `b`, `s`) are omitted from written wire entries.
- `rn`/`rq` are serialized as sorted unique arrays and omitted when empty.
- Cached public-API symbol payloads preserve declared parameter order; cache
  canonicalization must not reorder callable signatures.
- `ss` is written when source stats are available and is required for full cache-hit
  accounting in discovery stage.
- Legacy secret file `.cache_secret` is never used for trust; warning only.

Refs:

- `codeclone/cache.py:Cache.save`
- `codeclone/cache.py:_encode_wire_file_entry`
- `codeclone/pipeline.py:discover`
- `codeclone/cache.py:LEGACY_CACHE_SECRET_FILENAME`

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

- `codeclone/cache.py:CacheStatus`
- `codeclone/cli.py:_main_impl`

## Determinism / canonicalization

- Cache signatures are computed over canonical JSON payload.
- Wire file paths and row arrays are sorted before write.
- `rn`/`rq` are deterministically normalized to sorted unique arrays.
- Current schema decodes only the canonical row shapes that current runtime writes;
  for `u` rows, decoder accepts legacy 11-column layout and canonical 17-column
  layout (missing structural columns default to neutral values).
- `sr` is additive and optional; invalid/missing projection never invalidates the
  cache and simply falls back to runtime recomputation.

Refs:

- `codeclone/cache.py:_canonical_json`
- `codeclone/cache.py:_wire_filepath_from_runtime`
- `codeclone/cache.py:_encode_wire_file_entry`

## Locked by tests

- `tests/test_cache.py::test_cache_v13_uses_relpaths_when_root_set`
- `tests/test_cache.py::test_cache_load_analysis_profile_mismatch`
- `tests/test_cache.py::test_cache_signature_validation_ignores_json_whitespace`
- `tests/test_cache.py::test_cache_signature_mismatch_warns`
- `tests/test_cache.py::test_cache_too_large_warns`
- `tests/test_cli_inprocess.py::test_cli_reports_cache_too_large_respects_max_size_flag`
- `tests/test_cli_inprocess.py::test_cli_cache_analysis_profile_compatibility`
- `tests/test_pipeline_metrics.py::test_load_cached_metrics_ignores_referenced_names_from_test_files`

## Non-guarantees

- Cache file content stability across schema bumps is not guaranteed.
- Cache payload is tamper-evident only; it is not secret-authenticated.
