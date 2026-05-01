# 04. Config and Defaults

## Purpose

Describe effective runtime configuration and defaults that affect behavior.

## Public surface

- Option specs/defaults: `codeclone/config/spec.py`
- CLI parser and defaults: `codeclone/config/argparse_builder.py:build_parser`
- Pyproject config loader: `codeclone/config/pyproject_loader.py:load_pyproject_config`
- Config resolver: `codeclone/config/resolver.py:resolve_config`
- Effective cache default path logic: `codeclone/surfaces/cli/runtime.py:_resolve_cache_path`
- Metrics-mode selection logic: `codeclone/surfaces/cli/runtime.py:_configure_metrics_mode`
- Debug mode sources: `codeclone/surfaces/cli/console.py:_is_debug_enabled`

## Data model

Configuration sources, in precedence order:

1. CLI flags (`argparse`, explicit options only)
2. `pyproject.toml` section `[tool.codeclone]`
3. Code defaults in parser and runtime

`CODECLONE_DEBUG=1` affects debug diagnostics only and is not part of analysis
or gating configuration precedence.

Key defaults:

- `root="."`
- `--min-loc=10`
- `--min-stmt=6`
- `--processes=4`
- `--baseline=codeclone.baseline.json`
- `--max-baseline-size-mb=5`
- `--max-cache-size-mb=50`
- `--coverage-min=50`
- default cache path (when no cache flag is given): `<root>/.cache/codeclone/cache.json`
- `--metrics-baseline=codeclone.baseline.json` (same default path as `--baseline`)
- bare reporting flags use default report paths:
    - `--html` -> `<root>/.cache/codeclone/report.html`
    - `--json` -> `<root>/.cache/codeclone/report.json`
    - `--md` -> `<root>/.cache/codeclone/report.md`
    - `--sarif` -> `<root>/.cache/codeclone/report.sarif`
    - `--text` -> `<root>/.cache/codeclone/report.txt`

Fragment-level admission thresholds (pyproject.toml only, advanced tuning):

- `block_min_loc=20` — minimum function LOC for block-level sliding window
- `block_min_stmt=8` — minimum function statements for block-level sliding window
- `segment_min_loc=20` — minimum function LOC for segment-level sliding window
- `segment_min_stmt=10` — minimum function statements for segment-level sliding window

Example project-level config:

```toml title="Minimal [tool.codeclone] configuration"
[tool.codeclone]
min_loc = 10
min_stmt = 6
baseline = "codeclone.baseline.json"
skip_metrics = true
quiet = true
```

Supported `[tool.codeclone]` keys in the current line:

`Requires / Implies` lists only runtime-enforced relationships from the current
code path. Use `-` when the key has no special dependency contract.

Analysis:

| Key                    | Type          | Default                              | Meaning                                                                                                                                       | Requires / Implies                                                 |
|------------------------|---------------|--------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------|
| `min_loc`              | `int`         | `10`                                 | Minimum function LOC for clone admission                                                                                                      | `-`                                                                |
| `min_stmt`             | `int`         | `6`                                  | Minimum function statement count for clone admission                                                                                          | `-`                                                                |
| `block_min_loc`        | `int`         | `20`                                 | Minimum function LOC for block-window analysis                                                                                                | `-`                                                                |
| `block_min_stmt`       | `int`         | `8`                                  | Minimum function statements for block-window analysis                                                                                         | `-`                                                                |
| `segment_min_loc`      | `int`         | `20`                                 | Minimum function LOC for segment analysis                                                                                                     | `-`                                                                |
| `segment_min_stmt`     | `int`         | `10`                                 | Minimum function statements for segment analysis                                                                                              | `-`                                                                |
| `processes`            | `int`         | `4`                                  | Worker process count                                                                                                                          | `-`                                                                |
| `cache_path`           | `str \| null` | `<root>/.cache/codeclone/cache.json` | Cache file path                                                                                                                               | `-`                                                                |
| `max_cache_size_mb`    | `int`         | `50`                                 | Maximum accepted cache size before fail-open ignore                                                                                           | `-`                                                                |
| `skip_metrics`         | `bool`        | `false*`                             | Skip full metrics mode when allowed                                                                                                           | Incompatible with metrics gates/update; auto-enabled in some runs* |
| `skip_dead_code`       | `bool`        | `false`                              | Skip dead-code analysis                                                                                                                       | Forced on by `skip_metrics`; overridden by `fail_dead_code`        |
| `skip_dependencies`    | `bool`        | `false`                              | Skip dependency analysis                                                                                                                      | Forced on by `skip_metrics`; overridden by `fail_cycles`           |
| `golden_fixture_paths` | `list[str]`   | `[]`                                 | Exclude clone groups fully contained in matching golden test fixtures from health/gates/active findings; keep them as suppressed report facts | Patterns must resolve under `tests/` or `tests/fixtures/`          |

Baseline and CI:

| Key                       | Type   | Default                   | Meaning                                   | Requires / Implies                                                                                              |
|---------------------------|--------|---------------------------|-------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| `baseline`                | `str`  | `codeclone.baseline.json` | Clone baseline path                       | Default target for `metrics_baseline` when not overridden                                                       |
| `max_baseline_size_mb`    | `int`  | `5`                       | Maximum accepted baseline size            | `-`                                                                                                             |
| `update_baseline`         | `bool` | `false`                   | Rewrite unified baseline from current run | In unified mode, auto-enables `update_metrics_baseline` unless `skip_metrics=true`                              |
| `metrics_baseline`        | `str`  | `codeclone.baseline.json` | Dedicated metrics-baseline path override  | Defaults to `baseline` path when not overridden                                                                 |
| `update_metrics_baseline` | `bool` | `false`                   | Rewrite metrics baseline from current run | Requires metrics analysis; may auto-enable `update_baseline` for missing shared baseline                        |
| `ci`                      | `bool` | `false`                   | Enable CI preset behavior                 | Implies `fail_on_new`, `no_color`, `quiet`; enables `fail_on_new_metrics` when a trusted metrics baseline loads |

Quality gates and metric collection:

| Key                            | Type          | Default | Meaning                                                                             | Requires / Implies                                                                                                   |
|--------------------------------|---------------|---------|-------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `fail_on_new`                  | `bool`        | `false` | Fail when new clone groups appear                                                   | Requires a trusted clone baseline                                                                                    |
| `fail_threshold`               | `int`         | `-1`    | Fail when clone count exceeds threshold                                             | `-`                                                                                                                  |
| `fail_complexity`              | `int`         | `-1`    | Fail when max cyclomatic complexity exceeds threshold                               | Incompatible with `skip_metrics`                                                                                     |
| `fail_coupling`                | `int`         | `-1`    | Fail when max CBO exceeds threshold                                                 | Incompatible with `skip_metrics`                                                                                     |
| `fail_cohesion`                | `int`         | `-1`    | Fail when max LCOM4 exceeds threshold                                               | Incompatible with `skip_metrics`                                                                                     |
| `fail_cycles`                  | `bool`        | `false` | Fail when dependency cycles are present                                             | Incompatible with `skip_metrics`; forces dependency analysis                                                         |
| `fail_dead_code`               | `bool`        | `false` | Fail when high-confidence dead code is present                                      | Incompatible with `skip_metrics`; forces dead-code analysis                                                          |
| `fail_health`                  | `int`         | `-1`    | Fail when health score drops below threshold                                        | Incompatible with `skip_metrics`                                                                                     |
| `fail_on_new_metrics`          | `bool`        | `false` | Fail on new metric hotspots vs trusted metrics baseline                             | Requires trusted metrics baseline; incompatible with `skip_metrics`; auto-enabled by `ci` when baseline loads        |
| `api_surface`                  | `bool`        | `false` | Collect public API inventory/diff facts                                             | Auto-enabled by `fail_on_api_break`                                                                                  |
| `coverage_xml`                 | `str \| null` | `null`  | Join external Cobertura XML to current-run function spans                           | Enables Coverage Join                                                                                                |
| `coverage_min`                 | `int`         | `50`    | Coverage threshold for joined measured coverage hotspots                            | Used by Coverage Join; meaningful with `coverage_xml`                                                                |
| `min_typing_coverage`          | `int`         | `-1`    | Minimum allowed typing coverage percent                                             | Incompatible with `skip_metrics`                                                                                     |
| `min_docstring_coverage`       | `int`         | `-1`    | Minimum allowed docstring coverage percent                                          | Incompatible with `skip_metrics`                                                                                     |
| `fail_on_typing_regression`    | `bool`        | `false` | Fail on typing coverage regression vs metrics baseline                              | Requires trusted metrics baseline with adoption snapshot; incompatible with `skip_metrics`                           |
| `fail_on_docstring_regression` | `bool`        | `false` | Fail on docstring coverage regression vs metrics baseline                           | Requires trusted metrics baseline with adoption snapshot; incompatible with `skip_metrics`                           |
| `fail_on_api_break`            | `bool`        | `false` | Fail on public API breaking changes vs metrics baseline                             | Requires trusted metrics baseline with API surface snapshot; incompatible with `skip_metrics`; implies `api_surface` |
| `fail_on_untested_hotspots`    | `bool`        | `false` | Fail when medium/high-risk functions measured by Coverage Join fall below threshold | Incompatible with `skip_metrics`; requires successful Coverage Join to fire                                          |

Report outputs and local UX:

| Key           | Type          | Default | Meaning                        | Requires / Implies                     |
|---------------|---------------|---------|--------------------------------|----------------------------------------|
| `html_out`    | `str \| null` | `null`  | HTML report output path        | `-`                                    |
| `json_out`    | `str \| null` | `null`  | JSON report output path        | `-`                                    |
| `md_out`      | `str \| null` | `null`  | Markdown report output path    | `-`                                    |
| `sarif_out`   | `str \| null` | `null`  | SARIF report output path       | `-`                                    |
| `text_out`    | `str \| null` | `null`  | Plain-text report output path  | `-`                                    |
| `no_progress` | `bool`        | `false` | Disable progress UI            | Implied by `quiet`                     |
| `no_color`    | `bool`        | `false` | Disable colored CLI output     | Enabled by `ci`                        |
| `quiet`       | `bool`        | `false` | Use compact CLI output         | Implies `no_progress`; enabled by `ci` |
| `verbose`     | `bool`        | `false` | Enable more verbose CLI output | `-`                                    |
| `debug`       | `bool`        | `false` | Enable debug diagnostics       | Also enabled by `CODECLONE_DEBUG=1`    |

This is the exact accepted `[tool.codeclone]` key set from
`codeclone/config/spec.py` and `codeclone/config/pyproject_loader.py`; unknown
keys are contract errors.

!!! note "Pyproject keys vs CLI flags"
    The tables above list `[tool.codeclone]` keys, not CLI flag spellings.
    CLI flags may map to the same internal destination under a different name.
    Example: `coverage_xml` in `pyproject.toml` corresponds to CLI
    `--coverage FILE`. The same pattern applies to report outputs such as
    `html_out` ↔ `--html` and `json_out` ↔ `--json`.

!!! warning "Metrics-mode conflicts are enforced"
    Metrics update/gating flags are runtime contracts, not hints. Combinations
    such as `skip_metrics=true` together with metrics gating or metrics
    baseline update flags are contract errors.

Notes:

- `skip_metrics=false*`: parser default is `false`, but runtime may auto-enable
  it when no metrics work is requested and no metrics baseline exists.
- Report output keys default to `null`; bare CLI flags still write to the
  deterministic `.cache/codeclone/report.*` paths listed above.

CLI always has precedence when option is explicitly provided, including boolean
overrides via `--foo/--no-foo` (e.g. `--no-skip-metrics`).

Path values loaded from `pyproject.toml` are normalized relative to resolved
scan root when provided as relative paths.

`golden_fixture_paths` is different:

- entries are repo-relative glob patterns, not filesystem paths
- they are not normalized to absolute paths
- they must target `tests/` or `tests/fixtures/`
- a clone group is excluded only when every occurrence matches the configured
  golden-fixture scope

Current-run coverage join config:

- `coverage_xml` is the `[tool.codeclone]` key; the equivalent CLI flag is
  `--coverage FILE`.
- `coverage_xml` may be set in `pyproject.toml`; relative paths resolve from
  the scan root like other configured paths.
- `coverage_min` and `fail_on_untested_hotspots` follow the same precedence
  rules as CLI flags.
- Coverage join remains current-run only and does not persist to baseline.

Dependency depth config note:

- `dependency_max_depth` is an observed metric in reports/baselines, not a
  CLI or `pyproject.toml` option.
- Dependency depth now uses an internal adaptive profile based on
  `avg_depth`, `p95_depth`, and `max_depth` for the internal module graph.
- There is no user-facing knob to tune that model in `2.0.0`.

Metrics baseline path selection contract:

- Relative `baseline` / `metrics_baseline` paths coming from defaults or
  `pyproject.toml` resolve from the analysis root.
- If `--metrics-baseline` is explicitly set, that path is used.
- If `metrics_baseline` in `pyproject.toml` differs from parser default, that
  configured path is used even without explicit CLI flag.
- Otherwise, metrics baseline defaults to the clone baseline path.
- In other words, metrics do **not** live in a separate file by default:
  the default unified flow uses the same `codeclone.baseline.json` path for
  clone and metrics comparison state.

Refs:

- `codeclone/config/spec.py`
- `codeclone/config/argparse_builder.py:build_parser`
- `codeclone/config/pyproject_loader.py:load_pyproject_config`
- `codeclone/config/resolver.py:resolve_config`
- `codeclone/surfaces/cli/workflow.py:_main_impl`
- `codeclone/surfaces/cli/runtime.py:_configure_metrics_mode`

## Contracts

- `--ci` is a preset: enables `fail_on_new`, `no_color`, `quiet`.
- In CI mode, if trusted metrics baseline is loaded, runtime also enables
  `fail_on_new_metrics`.
- `--quiet` implies `--no-progress`.
- Negative size limits are contract errors.

Refs:

- `codeclone/surfaces/cli/workflow.py:_main_impl`

## Invariants (MUST)

- Detection thresholds (`min-loc`, `min-stmt`) affect function-level extraction.
- Fragment thresholds (`block_min_loc/stmt`, `segment_min_loc/stmt`) affect block/segment extraction.
- All six thresholds are part of cache compatibility (`payload.ap`).
- Reporting flags (`--html/--json/--md/--sarif/--text`) affect output only.
- Reporting flags accept optional path values; passing bare flag writes to
  deterministic default path under `.cache/codeclone/`.
- `--cache-path` overrides project-local cache default; legacy alias `--cache-dir` maps to same destination.
- Metrics baseline update/gating flags require metrics mode; incompatible
  combinations with `--skip-metrics` are contract errors.
- Unknown keys or invalid value types in `[tool.codeclone]` are contract errors (exit 2).

Refs:

- `codeclone/analysis/units.py:extract_units_and_stats_from_source`
- `codeclone/config/spec.py`
- `codeclone/config/argparse_builder.py:build_parser`
- `codeclone/surfaces/cli/runtime.py:_configure_metrics_mode`

## Failure modes

| Condition                     | Behavior           |
|-------------------------------|--------------------|
| Invalid output extension/path | Contract error (2) |
| Invalid root path             | Contract error (2) |
| Negative size limits          | Contract error (2) |

Refs:

- `codeclone/surfaces/cli/reports_output.py:_validate_output_path`
- `codeclone/surfaces/cli/startup.py:resolve_existing_root_path`
- `codeclone/surfaces/cli/workflow.py:_main_impl`

## Determinism / canonicalization

- Parser help text and epilog are deterministic constants.
- Summary metric labels are deterministic constants.

Refs:

- `codeclone/contracts/__init__.py:cli_help_epilog`
- `codeclone/ui_messages/__init__.py:SUMMARY_LABEL_FILES_FOUND`

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
