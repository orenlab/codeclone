# 04. Config and Defaults

## Purpose

Describe effective runtime configuration and defaults that affect behavior.

## Public surface

- CLI parser and defaults: `codeclone/_cli_args.py:build_parser`
- Pyproject config loader: `codeclone/_cli_config.py`
- Effective cache default path logic: `codeclone/cli.py:_resolve_cache_path`
- Metrics-mode selection logic: `codeclone/cli.py:_configure_metrics_mode`
- Debug mode sources: `codeclone/cli.py:_is_debug_enabled`

## Data model

Configuration sources, in precedence order:

1. CLI flags (`argparse`, explicit options only)
2. `pyproject.toml` section `[tool.codeclone]`
3. Code defaults in parser and runtime

`CODECLONE_DEBUG=1` affects debug diagnostics only and is not part of analysis
or gating configuration precedence.

Key defaults:

- `root="."`
- `--min-loc=15`
- `--min-stmt=6`
- `--processes=4`
- `--baseline=codeclone.baseline.json`
- `--max-baseline-size-mb=5`
- `--max-cache-size-mb=50`
- default cache path (when no cache flag is given): `<root>/.cache/codeclone/cache.json`
- `--metrics-baseline=codeclone.baseline.json` (same default path as `--baseline`)
- bare reporting flags use default report paths:
    - `--html` -> `<root>/.cache/codeclone/report.html`
    - `--json` -> `<root>/.cache/codeclone/report.json`
    - `--md` -> `<root>/.cache/codeclone/report.md`
    - `--sarif` -> `<root>/.cache/codeclone/report.sarif`
    - `--text` -> `<root>/.cache/codeclone/report.txt`

Example project-level config:

```toml
[tool.codeclone]
min_loc = 20
min_stmt = 8
baseline = "codeclone.baseline.json"
skip_metrics = true
quiet = true
```

CLI always has precedence when option is explicitly provided, including boolean
overrides via `--foo/--no-foo` (e.g. `--no-skip-metrics`).

Path values loaded from `pyproject.toml` are normalized relative to resolved
scan root when provided as relative paths.

Metrics baseline path selection contract:

- If `--metrics-baseline` is explicitly set, that path is used.
- If `metrics_baseline` in `pyproject.toml` differs from parser default, that
  configured path is used even without explicit CLI flag.
- Otherwise, metrics baseline defaults to the clone baseline path.

Refs:

- `codeclone/_cli_args.py:build_parser`
- `codeclone/cli.py:_main_impl`
- `codeclone/cli.py:_configure_metrics_mode`

## Contracts

- `--ci` is a preset: enables `fail_on_new`, `no_color`, `quiet`.
- In CI mode, if trusted metrics baseline is loaded, runtime also enables
  `fail_on_new_metrics`.
- `--quiet` implies `--no-progress`.
- Negative size limits are contract errors.

Refs:

- `codeclone/cli.py:_main_impl`

## Invariants (MUST)

- Detection thresholds (`min-loc`, `min-stmt`) affect extraction.
- Detection thresholds (`min-loc`, `min-stmt`) are part of cache compatibility (`payload.ap`).
- Reporting flags (`--html/--json/--md/--sarif/--text`) affect output only.
- Reporting flags accept optional path values; passing bare flag writes to
  deterministic default path under `.cache/codeclone/`.
- `--cache-path` overrides project-local cache default; legacy alias `--cache-dir` maps to same destination.
- Metrics baseline update/gating flags require metrics mode; incompatible
  combinations with `--skip-metrics` are contract errors.
- Unknown keys or invalid value types in `[tool.codeclone]` are contract errors (exit 2).

Refs:

- `codeclone/extractor.py:extract_units_and_stats_from_source`
- `codeclone/_cli_args.py:build_parser`
- `codeclone/cli.py:_configure_metrics_mode`

## Failure modes

| Condition                     | Behavior           |
|-------------------------------|--------------------|
| Invalid output extension/path | Contract error (2) |
| Invalid root path             | Contract error (2) |
| Negative size limits          | Contract error (2) |

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

## See also

- [09-cli.md](09-cli.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
