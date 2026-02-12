# 09. CLI

## Purpose
Define observable CLI behavior: argument handling, summaries, error UI, and output writing.

## Public surface
- CLI runner: `codeclone/cli.py:main`, `codeclone/cli.py:_main_impl`
- Parser: `codeclone/_cli_args.py:build_parser`
- Summary renderer: `codeclone/_cli_summary.py:_print_summary`
- Path validation: `codeclone/_cli_paths.py:_validate_output_path`
- Message catalog: `codeclone/ui_messages.py`

## Data model
CLI modes:
- Normal mode
- Gating mode (`--ci`, `--fail-on-new`, `--fail-threshold>=0`)
- Update mode (`--update-baseline`)

Summary metrics:
- files found/analyzed/cache hits/skipped
- function/block/segment groups
- suppressed segment groups
- new vs baseline

Refs:
- `codeclone/_cli_summary.py:_build_summary_rows`

## Contracts
- Help output includes canonical exit-code section and project links.
- Contract errors are prefixed by `CONTRACT ERROR:`.
- Gating failures are prefixed by `GATING FAILURE:`.
- Internal errors use `fmt_internal_error` with optional debug details.

Refs:
- `codeclone/contracts.py:cli_help_epilog`
- `codeclone/ui_messages.py:fmt_contract_error`
- `codeclone/ui_messages.py:fmt_internal_error`

## Invariants (MUST)
- Report writes (`--html/--json/--text`) are path-validated and write failures are contract errors.
- Baseline update write failure is contract error.
- In gating mode, unreadable source files are contract errors with higher priority than clone gating failure.

Refs:
- `codeclone/cli.py:_write_report_output`
- `codeclone/cli.py:_main_impl`

## Failure modes
| Condition | User-facing category | Exit |
| --- | --- | --- |
| Invalid CLI flag | contract | 2 |
| Invalid output extension/path | contract | 2 |
| Baseline untrusted in CI/gating | contract | 2 |
| Unreadable source in CI/gating | contract | 2 |
| New clones with `--fail-on-new` | gating | 3 |
| Threshold exceeded | gating | 3 |
| Unexpected exception | internal | 5 |

## Determinism / canonicalization
- Summary metric ordering is fixed.
- Compact summary mode (`--quiet`) is fixed-format text.
- Help epilog is generated from static constants.

Refs:
- `codeclone/_cli_summary.py:_build_summary_rows`
- `codeclone/contracts.py:EXIT_CODE_DESCRIPTIONS`

## Locked by tests
- `tests/test_cli_unit.py::test_cli_help_text_consistency`
- `tests/test_cli_unit.py::test_argument_parser_contract_error_marker_for_invalid_args`
- `tests/test_cli_inprocess.py::test_cli_summary_format_stable`
- `tests/test_cli_inprocess.py::test_cli_unreadable_source_fails_in_ci_with_contract_error`
- `tests/test_cli_inprocess.py::test_cli_contract_error_priority_over_gating_failure_for_unreadable_source`

## Non-guarantees
- Rich styling details are not part of machine-facing CLI contract.
- Warning phrasing may evolve if category markers and exit semantics stay stable.
