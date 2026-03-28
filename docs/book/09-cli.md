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
- structural counters: analyzed lines/functions/methods/classes
- function/block/segment groups
- suppressed segment groups
- dead-code active/suppressed status in metrics line
- new vs baseline

Refs:

- `codeclone/_cli_summary.py:_print_summary`
- `codeclone/ui_messages.py:fmt_summary_files`

## Contracts

- Help output includes canonical exit-code section and project links.
- Reporting flag UX uses explicit pairs (`--no-progress`/`--progress`,
  `--no-color`/`--color`) and avoids generated double-negation aliases.
- `--open-html-report` is a local UX action layered on top of `--html`; it does not implicitly enable HTML output.
- `--timestamped-report-paths` only rewrites default report paths requested via bare report flags; explicit FILE values
  stay unchanged.
- Changed-scope clone review uses:
    - `--changed-only`
    - `--diff-against GIT_REF`
    - `--paths-from-git-diff GIT_REF`
      Typical usage:
    - `codeclone . --changed-only --diff-against main`
    - `codeclone . --paths-from-git-diff HEAD~1`
- Contract errors are prefixed by `CONTRACT ERROR:`.
- Gating failures are prefixed by `GATING FAILURE:`.
- Internal errors use `fmt_internal_error` with optional debug details.
- Runtime footer uses explicit wording: `Pipeline done in <seconds>s`.
  This metric is CLI pipeline time and does not include external launcher/startup overhead (for example `uv run`).
- Dead-code metric line is stateful and deterministic:
    - `N found (M suppressed)` when active dead-code items exist
    - `✔ clean` when both active and suppressed are zero
    - `✔ clean (M suppressed)` when active is zero but suppressed > 0

Refs:

- `codeclone/contracts.py:cli_help_epilog`
- `codeclone/ui_messages.py:fmt_contract_error`
- `codeclone/ui_messages.py:fmt_internal_error`

## Invariants (MUST)

- Report writes (`--html/--json/--md/--sarif/--text`) are path-validated and write failures are contract errors.
- Bare reporting flags write to default deterministic paths under
  `.cache/codeclone/`.
- `--open-html-report` requires `--html`; invalid combination is a contract error.
- `--timestamped-report-paths` requires at least one requested report output; invalid combination is a contract error.
- `--changed-only` requires either `--diff-against` or `--paths-from-git-diff`.
- `--diff-against` requires `--changed-only`.
- `--diff-against` and `--paths-from-git-diff` are mutually exclusive.
- Browser-open failure after a successful HTML write is warning-only and does not change the process exit code.
- Baseline update write failure is contract error.
- In gating mode, unreadable source files are contract errors with higher priority than clone gating failure.
- Changed-scope flags do not create a second canonical report: they project clone
  summary/threshold decisions over the changed-files subset after the normal full
  analysis completes.

Refs:

- `codeclone/cli.py:_write_report_output`
- `codeclone/cli.py:_main_impl`

## Failure modes

| Condition                                    | User-facing category | Exit |
|----------------------------------------------|----------------------|------|
| Invalid CLI flag                             | contract             | 2    |
| Invalid output extension/path                | contract             | 2    |
| `--open-html-report` without `--html`        | contract             | 2    |
| `--timestamped-report-paths` without reports | contract             | 2    |
| `--changed-only` without diff source         | contract             | 2    |
| `--diff-against` without `--changed-only`    | contract             | 2    |
| `--diff-against` + `--paths-from-git-diff`   | contract             | 2    |
| Baseline untrusted in CI/gating              | contract             | 2    |
| Unreadable source in CI/gating               | contract             | 2    |
| New clones with `--fail-on-new`              | gating               | 3    |
| Threshold exceeded                           | gating               | 3    |
| Unexpected exception                         | internal             | 5    |

## Determinism / canonicalization

- Summary metric ordering is fixed.
- Compact summary mode (`--quiet`) is fixed-format text.
- Help epilog is generated from static constants.
- `git diff --name-only` input is normalized to sorted repo-relative paths before
  changed-scope projection is applied.

Refs:

- `codeclone/_cli_summary.py:_print_summary`
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

## See also

- [04-config-and-defaults.md](04-config-and-defaults.md)
- [20-mcp-interface.md](20-mcp-interface.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
- [16-dead-code-contract.md](16-dead-code-contract.md)
