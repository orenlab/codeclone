# 03. Contracts: Exit Codes

## Purpose
Define stable process exit semantics and category boundaries.

## Public surface
- Exit enum: `codeclone/contracts.py:ExitCode`
- CLI categorization and exits: `codeclone/cli.py:_main_impl`, `codeclone/cli.py:main`
- Error markers: `codeclone/ui_messages.py`

## Data model
| Exit code | Category | Meaning |
| --- | --- | --- |
| 0 | success | Run completed without gating failures |
| 2 | contract error | Input/contract violation (baseline trust, output path/ext, unreadable source in gating) |
| 3 | gating failure | Analysis succeeded but policy failed (`--fail-on-new`, `--fail-threshold`) |
| 5 | internal error | Unexpected exception escaped `_main_impl` |

Refs:
- `codeclone/contracts.py:ExitCode`
- `codeclone/_cli_args.py:_ArgumentParser.error`

## Contracts
- Contract errors must use `CONTRACT ERROR:` marker.
- Gating failures must use `GATING FAILURE:` marker.
- Internal errors are formatted by `fmt_internal_error`; traceback hidden unless debug enabled.

Refs:
- `codeclone/ui_messages.py:fmt_contract_error`
- `codeclone/ui_messages.py:fmt_gating_failure`
- `codeclone/ui_messages.py:fmt_internal_error`

## Invariants (MUST)
- `SystemExit` from contract/gating paths must pass through `main()` unchanged.
- Only non-`SystemExit` exceptions in `main()` become exit 5.
- In gating mode, unreadable source files force exit 2 even if clone gating would also fail.

Refs:
- `codeclone/cli.py:main`
- `codeclone/cli.py:_main_impl`

## Failure modes
| Condition | Marker | Exit |
| --- | --- | --- |
| Invalid output extension | CONTRACT ERROR | 2 |
| Untrusted baseline in CI/gating | CONTRACT ERROR | 2 |
| Unreadable source in CI/gating | CONTRACT ERROR | 2 |
| New clones with `--fail-on-new` | GATING FAILURE | 3 |
| Threshold exceeded | GATING FAILURE | 3 |
| Unexpected exception in main pipeline | INTERNAL ERROR | 5 |

## Determinism / canonicalization
- Help epilog strings are generated from static constants.
- Error category markers are static constants.

Refs:
- `codeclone/contracts.py:cli_help_epilog`
- `codeclone/ui_messages.py:MARKER_CONTRACT_ERROR`

## Locked by tests
- `tests/test_cli_unit.py::test_cli_help_text_consistency`
- `tests/test_cli_unit.py::test_cli_internal_error_marker`
- `tests/test_cli_unit.py::test_cli_internal_error_debug_flag_includes_traceback`
- `tests/test_cli_inprocess.py::test_cli_unreadable_source_fails_in_ci_with_contract_error`
- `tests/test_cli_inprocess.py::test_cli_contract_error_priority_over_gating_failure_for_unreadable_source`

## Non-guarantees
- Exact message body text may evolve; category marker and exit code are contract.
