# 09. CLI

## Purpose

Define observable CLI behavior: argument handling, summaries, output writing,
and exit routing.

## Public surface

- Public entrypoint: `codeclone/main.py:main`
- CLI orchestration: `codeclone/surfaces/cli/workflow.py:_main_impl`
- Parser: `codeclone/config/argparse_builder.py:build_parser`
- Summary renderer: `codeclone/surfaces/cli/summary.py:_print_summary`
- Output path validation and writes:
  `codeclone/surfaces/cli/reports_output.py`
- Message catalog: `codeclone/ui_messages/__init__.py`

## Data model

CLI modes:

- normal mode
- gating mode (`--ci`, `--fail-on-new`, explicit metric gates)
- baseline update mode (`--update-baseline`, `--update-metrics-baseline`)

Summary metrics include:

- files found/analyzed/cache hits/skipped
- structural counters for lines/functions/methods/classes
- function/block/segment clone groups
- suppressed clone groups from `golden_fixture_paths`
- dead-code active/suppressed status
- adoption/API/coverage-join facts when computed
- new vs baseline

Refs:

- `codeclone/surfaces/cli/summary.py:_print_summary`
- `codeclone/surfaces/cli/runtime.py:_metrics_flags_requested`
- `codeclone/surfaces/cli/runtime.py:_metrics_computed`
- `codeclone/surfaces/cli/report_meta.py:_build_report_meta`

## Contracts

- Help output includes canonical exit-code section and project links.
- Bare report flags write to deterministic default paths under `.cache/codeclone/`.
- `--open-html-report` is layered on top of `--html`; it does not imply HTML output.
- `--timestamped-report-paths` rewrites only default report paths requested via bare flags.
- Changed-scope review uses:
    - `--changed-only`
    - `--diff-against`
    - `--paths-from-git-diff`
- Contract errors use `CONTRACT ERROR:`.
- Gating failures use `GATING FAILURE:`.
- Internal errors use `fmt_internal_error` and include traceback only in debug mode.

Refs:

- `codeclone/contracts/__init__.py:cli_help_epilog`
- `codeclone/ui_messages/__init__.py:fmt_contract_error`
- `codeclone/ui_messages/__init__.py:fmt_internal_error`
- `codeclone/surfaces/cli/changed_scope.py:_validate_changed_scope_args`

## Invariants (MUST)

- Report writes are path-validated and write failures are contract errors.
- `--open-html-report` requires `--html`.
- `--timestamped-report-paths` requires at least one requested report output.
- `--changed-only` requires a diff source.
- Browser-open failure after successful HTML write is warning-only.
- In gating mode, unreadable source files are contract errors with higher priority than clone/metric gate failures.

Refs:

- `codeclone/surfaces/cli/reports_output.py:_validate_output_path`
- `codeclone/surfaces/cli/reports_output.py:_validate_report_ui_flags`
- `codeclone/surfaces/cli/workflow.py:_main_impl`

## Failure modes

| Condition                                                         | User-facing category | Exit |
|-------------------------------------------------------------------|----------------------|------|
| Invalid CLI flag                                                  | contract             | `2`  |
| Invalid output extension/path                                     | contract             | `2`  |
| Invalid changed-scope flag combination                            | contract             | `2`  |
| Baseline untrusted in CI/gating                                   | contract             | `2`  |
| Coverage/API regression gate without required baseline capability | contract             | `2`  |
| Unreadable source in CI/gating                                    | contract             | `2`  |
| New clones with `--fail-on-new`                                   | gating               | `3`  |
| Threshold or metrics gate exceeded                                | gating               | `3`  |
| Unexpected exception                                              | internal             | `5`  |

## Determinism / canonicalization

- Summary metric ordering is fixed.
- Compact summary mode is fixed-format text.
- Help epilog is generated from static constants.
- Git diff path inputs are normalized to sorted repo-relative paths.

Refs:

- `codeclone/surfaces/cli/summary.py:_print_summary`
- `codeclone/contracts/__init__.py:cli_help_epilog`
- `codeclone/surfaces/cli/changed_scope.py:_normalize_changed_paths`

## Locked by tests

- `tests/test_cli_unit.py::test_cli_help_text_consistency`
- `tests/test_cli_unit.py::test_argument_parser_contract_error_marker_for_invalid_args`
- `tests/test_cli_inprocess.py::test_cli_summary_format_stable`
- `tests/test_cli_inprocess.py::test_cli_unreadable_source_fails_in_ci_with_contract_error`
- `tests/test_cli_inprocess.py::test_cli_contract_error_priority_over_gating_failure_for_unreadable_source`

## Non-guarantees

- Rich styling details are not machine-facing contract.
- Warning phrasing may evolve if category markers and exit semantics stay stable.
