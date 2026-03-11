# 07. Cache

## Purpose

Define cache schema v2.1, integrity verification, and fail-open behavior.

## Public surface

- Cache object lifecycle: `codeclone/cache.py:Cache`
- Cache statuses: `codeclone/cache.py:CacheStatus`
- Stat signature source: `codeclone/cache.py:file_stat_signature`
- CLI cache integration: `codeclone/cli.py:_main_impl`

## Data model

On-disk schema (`v == "2.1"`):

- Top-level: `v`, `payload`, `sig`
- `payload` keys: `py`, `fp`, `ap`, `files`
- `ap` (`analysis_profile`) keys: `min_loc`, `min_stmt`
- `files` map stores compact per-file entries:
    - `st`: `[mtime_ns, size]`
    - optional analysis sections (`u`/`b`/`s` and metrics-related sections)
- file keys are wire relpaths when `root` is configured
- per-file `dc` (`dead_candidates`) rows do not repeat filepath; path is implied by
  the containing file entry

Refs:

- `codeclone/cache.py:Cache.load`
- `codeclone/cache.py:_encode_wire_file_entry`
- `codeclone/cache.py:_decode_wire_file_entry`

## Contracts

- Cache is optimization-only; invalid cache never blocks analysis.
- Any cache trust failure triggers warning + empty cache fallback.
- Cache compatibility gates:
    - version `v == CACHE_VERSION`
    - `payload.py == current_python_tag()`
    - `payload.fp == BASELINE_FINGERPRINT_VERSION`
    - `payload.ap == {"min_loc": <runtime>, "min_stmt": <runtime>}`
    - `sig` equals deterministic hash of canonical payload

Refs:

- `codeclone/cache.py:Cache.load`
- `codeclone/cache.py:Cache._ignore_cache`
- `codeclone/cache.py:Cache._sign_data`

## Invariants (MUST)

- Cache save writes canonical JSON and atomically replaces target file.
- Empty sections (`u`, `b`, `s`) are omitted from written wire entries.
- Legacy secret file `.cache_secret` is never used for trust; warning only.

Refs:

- `codeclone/cache.py:Cache.save`
- `codeclone/cache.py:_encode_wire_file_entry`
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
- Current schema decodes only the canonical row shapes that current runtime writes;
  older cache schemas are ignored and rebuilt.

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

## Non-guarantees

- Cache file content stability across schema bumps is not guaranteed.
- Cache payload is tamper-evident only; it is not secret-authenticated.
