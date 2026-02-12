# Appendix A. Status Enums

## Purpose
Centralize machine-readable status value sets used across baseline/cache/report contracts.

## Public surface
- Baseline statuses: `codeclone/baseline.py:BaselineStatus`
- Cache statuses: `codeclone/cache.py:CacheStatus`
- Exit categories: `codeclone/contracts.py:ExitCode`

## Data model
### BaselineStatus
- `ok`
- `missing`
- `too_large`
- `invalid_json`
- `invalid_type`
- `missing_fields`
- `mismatch_schema_version`
- `mismatch_fingerprint_version`
- `mismatch_python_version`
- `generator_mismatch`
- `integrity_missing`
- `integrity_failed`

### Baseline untrusted set
Defined by `BASELINE_UNTRUSTED_STATUSES`.

### CacheStatus
- `ok`
- `missing`
- `too_large`
- `unreadable`
- `invalid_json`
- `invalid_type`
- `version_mismatch`
- `python_tag_mismatch`
- `mismatch_fingerprint_version`
- `integrity_failed`

### ExitCode
- `0` success
- `2` contract error
- `3` gating failure
- `5` internal error

## Contracts
- Status values are serialized into report metadata (`baseline_status`, `cache_status`).
- CLI branches by enum values, not UI text.

Refs:
- `codeclone/_cli_meta.py:ReportMeta`
- `codeclone/cli.py:_main_impl`

## Locked by tests
- `tests/test_baseline.py::test_coerce_baseline_status`
- `tests/test_cache.py::test_cache_version_mismatch_warns`
- `tests/test_cli_unit.py::test_cli_help_text_consistency`

## Non-guarantees
- Human-readable status messages can change while enum values stay stable.
