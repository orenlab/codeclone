# Appendix C. Error Catalog

## Purpose
Map core error conditions to statuses, markers, and exits.

## Contract/gating/internal categories
| Category | Marker | Exit |
| --- | --- | --- |
| Contract error | `CONTRACT ERROR:` | 2 |
| Gating failure | `GATING FAILURE:` | 3 |
| Internal error | `INTERNAL ERROR:` | 5 |

Refs:
- `codeclone/ui_messages.py:MARKER_CONTRACT_ERROR`
- `codeclone/contracts.py:ExitCode`

## Baseline contract errors
| Condition | Baseline status | CLI behavior |
| --- | --- | --- |
| Missing baseline | `missing` | normal: empty diff; gating: exit 2 |
| Schema mismatch | `mismatch_schema_version` | normal: ignore baseline; gating: exit 2 |
| Fingerprint mismatch | `mismatch_fingerprint_version` | normal: ignore baseline; gating: exit 2 |
| Python tag mismatch | `mismatch_python_version` | normal: ignore baseline; gating: exit 2 |
| Integrity mismatch | `integrity_failed` | normal: ignore baseline; gating: exit 2 |

Refs:
- `codeclone/cli.py:_main_impl`
- `codeclone/baseline.py:BaselineStatus`

## Cache degradation cases
| Condition | Cache status | Behavior |
| --- | --- | --- |
| Missing cache file | `missing` | proceed without cache |
| Version mismatch | `version_mismatch` | ignore cache + warning |
| Invalid JSON/type | `invalid_json` / `invalid_type` | ignore cache + warning |
| Signature mismatch | `integrity_failed` | ignore cache + warning |
| Oversized cache | `too_large` | ignore cache + warning |

Refs:
- `codeclone/cache.py:CacheStatus`
- `codeclone/cache.py:Cache._ignore_cache`

## Source IO and gating
| Condition | Behavior |
| --- | --- |
| Source read/decode failure in normal mode | file skipped; warning; continue |
| Source read/decode failure in gating mode | contract error exit 2 |

Refs:
- `codeclone/cli.py:process_file`
- `codeclone/cli.py:_main_impl`

## Report write errors
| Condition | Behavior |
| --- | --- |
| Baseline write OSError | contract error exit 2 |
| HTML/JSON/TXT write OSError | contract error exit 2 |

Refs:
- `codeclone/cli.py:_main_impl`

## Locked by tests
- `tests/test_cli_inprocess.py::test_cli_report_write_error_is_contract_error`
- `tests/test_cli_inprocess.py::test_cli_update_baseline_write_error_is_contract_error`
- `tests/test_cli_inprocess.py::test_cli_unreadable_source_fails_in_ci_with_contract_error`
- `tests/test_cli_unit.py::test_cli_internal_error_marker`
