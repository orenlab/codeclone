# 04. Config and Defaults

## Purpose
Describe effective runtime configuration and defaults that affect behavior.

## Public surface
- CLI parser and defaults: `codeclone/_cli_args.py:build_parser`
- Effective cache default path logic: `codeclone/cli.py:_main_impl`
- Debug mode sources: `codeclone/cli.py:_is_debug_enabled`

## Data model
Configuration sources, in precedence order:
1. CLI flags (`argparse`)
2. Environment (`CODECLONE_DEBUG=1` for debug diagnostics)
3. Code defaults in parser and runtime

Key defaults:
- `root="."`
- `--min-loc=15`
- `--min-stmt=6`
- `--processes=4`
- `--baseline=codeclone.baseline.json`
- `--max-baseline-size-mb=5`
- `--max-cache-size-mb=50`
- default cache path (when no cache flag is given): `<root>/.cache/codeclone/cache.json`

Refs:
- `codeclone/_cli_args.py:build_parser`
- `codeclone/cli.py:_main_impl`

## Contracts
- `--ci` is a preset: enables `fail_on_new`, `no_color`, `quiet`.
- `--quiet` implies `--no-progress`.
- Negative size limits are contract errors.

Refs:
- `codeclone/cli.py:_main_impl`

## Invariants (MUST)
- Detection thresholds (`min-loc`, `min-stmt`) affect extraction.
- Reporting flags (`--html/--json/--text`) affect output only.
- `--cache-path` overrides project-local cache default; legacy alias `--cache-dir` maps to same destination.

Refs:
- `codeclone/extractor.py:extract_units_from_source`
- `codeclone/_cli_args.py:build_parser`

## Failure modes
| Condition | Behavior |
| --- | --- |
| Invalid output extension/path | Contract error (2) |
| Invalid root path | Contract error (2) |
| Negative size limits | Contract error (2) |

Refs:
- `codeclone/_cli_paths.py:_validate_output_path`
- `codeclone/cli.py:_main_impl`

## Determinism / canonicalization
- Parser help text and epilog are deterministic constants.
- Summary metric labels are deterministic constants.

Refs:
- `codeclone/contracts.py:cli_help_epilog`
- `codeclone/ui_messages.py:SUMMARY_LABEL_FILES_FOUND`

## Locked by tests
- `tests/test_cli_unit.py::test_cli_help_text_consistency`
- `tests/test_cli_inprocess.py::test_cli_default_cache_dir_uses_root`
- `tests/test_cli_inprocess.py::test_cli_cache_dir_override_respected`
- `tests/test_cli_inprocess.py::test_cli_negative_size_limits_fail_fast`

## Non-guarantees
- CLI help section ordering is stable today but not versioned independently from the CLI contract.
