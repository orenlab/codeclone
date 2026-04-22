# 03. Contracts: Exit Codes

## Purpose

Define stable process exit semantics and category boundaries.

## Public surface

- Exit enum: `codeclone/contracts/__init__.py:ExitCode`
- CLI entry: `codeclone/main.py:main`
- CLI orchestration: `codeclone/surfaces/cli/workflow.py:_main_impl`
- Error markers/formatters: `codeclone/ui_messages/__init__.py`

## Data model

| Exit code | Category       | Meaning                                             |
|-----------|----------------|-----------------------------------------------------|
| `0`       | success        | Run completed without gating failures               |
| `2`       | contract error | Input or contract violation                         |
| `3`       | gating failure | Analysis succeeded but policy failed                |
| `5`       | internal error | Unexpected exception escaped top-level CLI handling |

Refs:

- `codeclone/contracts/__init__.py:ExitCode`
- `codeclone/config/argparse_builder.py:_ArgumentParser.error`

## Contracts

- Contract errors use the `CONTRACT ERROR:` marker.
- Gating failures use the `GATING FAILURE:` marker.
- Internal errors use `INTERNAL ERROR:` and hide traceback unless debug is enabled.
- `main()` lets `SystemExit` from contract/gating paths pass through unchanged.

Refs:

- `codeclone/ui_messages/__init__.py:MARKER_CONTRACT_ERROR`
- `codeclone/ui_messages/__init__.py:MARKER_INTERNAL_ERROR`
- `codeclone/ui_messages/__init__.py:fmt_contract_error`
- `codeclone/ui_messages/__init__.py:fmt_gating_failure`
- `codeclone/ui_messages/__init__.py:fmt_internal_error`

## Invariants (MUST)

- Only non-`SystemExit` exceptions in `main()` become exit `5`.
- In gating mode, unreadable source files win over clone/metric gate failure and force exit `2`.

Refs:

- `codeclone/main.py:main`
- `codeclone/surfaces/cli/workflow.py:_main_impl`

## Failure modes

| Condition                                  | Marker           | Exit |
|--------------------------------------------|------------------|------|
| Invalid output extension/path              | `CONTRACT ERROR` | `2`  |
| Invalid CLI flag combination               | `CONTRACT ERROR` | `2`  |
| Untrusted baseline in CI/gating            | `CONTRACT ERROR` | `2`  |
| Unreadable source in CI/gating             | `CONTRACT ERROR` | `2`  |
| New clones with `--fail-on-new`            | `GATING FAILURE` | `3`  |
| Threshold or metrics gate breach           | `GATING FAILURE` | `3`  |
| Unexpected exception in top-level CLI path | `INTERNAL ERROR` | `5`  |

## Determinism / canonicalization

- Help epilog strings are generated from static constants.
- Error category markers are static constants.

Refs:

- `codeclone/contracts/__init__.py:cli_help_epilog`
- `codeclone/ui_messages/__init__.py:MARKER_CONTRACT_ERROR`

## Locked by tests

- `tests/test_cli_unit.py::test_cli_help_text_consistency`
- `tests/test_cli_unit.py::test_cli_internal_error_marker`
- `tests/test_cli_unit.py::test_cli_internal_error_debug_flag_includes_traceback`
- `tests/test_cli_inprocess.py::test_cli_unreadable_source_fails_in_ci_with_contract_error`
- `tests/test_cli_inprocess.py::test_cli_contract_error_priority_over_gating_failure_for_unreadable_source`

## Non-guarantees

- Exact message body wording may evolve; marker category and exit code are contract.
