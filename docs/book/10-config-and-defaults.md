<!-- doc-scope: CONFIGURATION REFERENCE — single home for all config keys.
     owns: all [tool.codeclone] keys, precedence rules, defaults, flag mapping,
     and all CODECLONE_* environment variable overrides.
     does-not-own: CLI behavior (→ 11), exit codes (→ 09), gate thresholds (→ 16).
     rule: stray flag docs from other chapters belong HERE. -->

# 10. Config and Defaults

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

Configuration sources for the main `codeclone` CLI scan, in precedence order:

1. CLI flags (`argparse`, explicit options only)
2. `pyproject.toml` section `[tool.codeclone]`
3. Code defaults in parser and runtime

Engineering Memory, the workspace intent registry, MCP session TTL/lease, and
other subsystems listed in [Environment variable overrides](#environment-variable-overrides)
may also read `CODECLONE_*` variables. Those overrides apply only to the
documented fields and do not change main CLI precedence unless noted.

Key defaults:

- `root="."`
- `--min-loc=10`
- `--min-stmt=6`
- `--processes=4`
- `--baseline=codeclone.baseline.json`
- `--max-baseline-size-mb=5`
- `--max-cache-size-mb=50`
- `--coverage-min=50`
- default cache path (when no cache flag is given): `<root>/.codeclone/cache.json`
- `--metrics-baseline=codeclone.baseline.json` (same default path as `--baseline`)
- bare reporting flags use default report paths:
    - `--html` -> `<root>/.codeclone/report.html`
    - `--json` -> `<root>/.codeclone/report.json`
    - `--md` -> `<root>/.codeclone/report.md`
    - `--sarif` -> `<root>/.codeclone/report.sarif`
    - `--text` -> `<root>/.codeclone/report.txt`
- legacy locations (CLI warns, does not migrate automatically):
    - home cache: `~/.cache/codeclone/cache.json` when it differs from the project cache path
    - repo workspace: non-empty `<root>/.cache/codeclone/` from releases before `2.1.0a1`

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

| Key                    | Type          | Default                        | Meaning                                                                                                                                       | Requires / Implies                                                 |
|------------------------|---------------|--------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------|
| `min_loc`              | `int`         | `10`                           | Minimum function LOC for clone admission                                                                                                      | `-`                                                                |
| `min_stmt`             | `int`         | `6`                            | Minimum function statement count for clone admission                                                                                          | `-`                                                                |
| `block_min_loc`        | `int`         | `20`                           | Minimum function LOC for block-window analysis                                                                                                | `-`                                                                |
| `block_min_stmt`       | `int`         | `8`                            | Minimum function statements for block-window analysis                                                                                         | `-`                                                                |
| `segment_min_loc`      | `int`         | `20`                           | Minimum function LOC for segment analysis                                                                                                     | `-`                                                                |
| `segment_min_stmt`     | `int`         | `10`                           | Minimum function statements for segment analysis                                                                                              | `-`                                                                |
| `processes`            | `int`         | `4`                            | Worker process count                                                                                                                          | `-`                                                                |
| `cache_path`           | `str \| null` | `<root>/.codeclone/cache.json` | Cache file path                                                                                                                               | `-`                                                                |
| `max_cache_size_mb`    | `int`         | `50`                           | Maximum accepted cache size before fail-open ignore                                                                                           | `-`                                                                |
| `skip_metrics`         | `bool`        | `false*`                       | Skip full metrics mode when allowed                                                                                                           | Incompatible with metrics gates/update; auto-enabled in some runs* |
| `skip_dead_code`       | `bool`        | `false`                        | Skip dead-code analysis                                                                                                                       | Forced on by `skip_metrics`; overridden by `fail_dead_code`        |
| `skip_dependencies`    | `bool`        | `false`                        | Skip dependency analysis                                                                                                                      | Forced on by `skip_metrics`; overridden by `fail_cycles`           |
| `golden_fixture_paths` | `list[str]`   | `[]`                           | Exclude clone groups fully contained in matching golden test fixtures from health/gates/active findings; keep them as suppressed report facts | Patterns must resolve under `tests/` or `tests/fixtures/`          |

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

| Key           | Type          | Default | Meaning                        | Requires / Implies                                                                      |
|---------------|---------------|---------|--------------------------------|-----------------------------------------------------------------------------------------|
| `html_out`    | `str \| null` | `null`  | HTML report output path        | `-`                                                                                     |
| `json_out`    | `str \| null` | `null`  | JSON report output path        | `-`                                                                                     |
| `md_out`      | `str \| null` | `null`  | Markdown report output path    | `-`                                                                                     |
| `sarif_out`   | `str \| null` | `null`  | SARIF report output path       | `-`                                                                                     |
| `text_out`    | `str \| null` | `null`  | Plain-text report output path  | `-`                                                                                     |
| `no_progress` | `bool`        | `false` | Disable progress UI            | Implied by `quiet`                                                                      |
| `no_color`    | `bool`        | `false` | Disable colored CLI output     | Enabled by `ci`                                                                         |
| `quiet`       | `bool`        | `false` | Use compact CLI output         | Implies `no_progress`; enabled by `ci`                                                  |
| `verbose`     | `bool`        | `false` | Enable more verbose CLI output | `-`                                                                                     |
| `debug`       | `bool`        | `false` | Enable debug diagnostics       | Also enabled by `CODECLONE_DEBUG`; see [env overrides](#environment-variable-overrides) |

Controller audit trail:

| Key                     | Type   | Default                       | Meaning                                                                                                                                                                      | Requires / Implies                  |
|-------------------------|--------|-------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------|
| `audit_enabled`         | `bool` | `false`                       | Enable the optional local controller audit trail                                                                                                                             | Required for `--audit` output       |
| `audit_path`            | `str`  | `.codeclone/db/audit.sqlite3` | SQLite audit database path, relative to the analysis root; stored under `db/` to separate controller state from report/cache artifacts                                       | Used only when `audit_enabled=true` |
| `audit_payloads`        | `str`  | `compact`                     | Audit payload mode: `off`, `compact`, or `full`. Compact omits large fields but keeps `intent_description` on `intent.declared`; row `summary` always stores a short essence | Used only when `audit_enabled=true` |
| `audit_retention_days`  | `int`  | `30`                          | Retention window for audit rows                                                                                                                                              | Used only when `audit_enabled=true` |
| `audit_token_estimator` | `str`  | `chars_approx`                | Audit payload token estimator: default `chars_approx`, or explicit `tiktoken` opt-in with `codeclone[token-bench]`                                                           | Used only when `audit_enabled=true` |

Workspace intent registry:

| Key                              | Type  | Default                         | Meaning                                                                  | Requires / Implies                              |
|----------------------------------|-------|---------------------------------|--------------------------------------------------------------------------|-------------------------------------------------|
| `intent_registry_backend`        | `str` | `file`                          | Workspace intent storage backend: `file` or `sqlite`                     | MCP workspace coordination                      |
| `intent_registry_path`           | `str` | `.codeclone/db/intents.sqlite3` | SQLite registry database path, relative to the analysis root             | Used only when `intent_registry_backend=sqlite` |
| `intent_registry_retention_days` | `int` | `7`                             | Retention window for closed SQLite intent rows (max `14` in open source) | Used only when `intent_registry_backend=sqlite` |

Values above `14` are contract errors in the open-source edition. See
[Plans and Retention](../plans-and-retention.md) for Team (up to 30 days) and
Enterprise (up to 90 days, PostgreSQL backend) options.

### Engineering Memory (nested tables)

Keys under `[tool.codeclone.memory]` and `[tool.codeclone.memory.semantic]` are
**not** part of the root `[tool.codeclone]` table above. They are validated by
`codeclone/config/memory.py` / `SemanticConfig` and documented in
[Engineering Memory](13-engineering-memory/index.md).

Trajectory / projection keys (defaults from `codeclone/config/memory_defaults.py`):

| Key                                        | Default    | Meaning                                                 |
|--------------------------------------------|------------|---------------------------------------------------------|
| trajectories_enabled                       | `true`     | Gate trajectory rebuild and retrieval                   |
| trajectory_retention_days                  | `365`      | Retention hint for vacuum                               |
| projection_rebuild_policy                  | `off`      | `enqueue_when_stale` enqueues worker on accepted finish |
| projection_rebuild_running_timeout_seconds | `1800`     | Stale running job timeout                               |
| projection_rebuild_spawn_worker            | `true`     | Spawn worker on enqueue                                 |
| trajectory_export_enabled                  | `false`    | Gate CLI JSONL export                                   |
| trajectory_export_include_payloads         | `false`    | Include step payloads in export rows                    |
| trajectory_export_max_record_bytes         | `65536`    | Per export row cap                                      |
| trajectory_export_max_file_bytes           | `10485760` | Output file cap                                         |

| Semantic field       | Default                                           | Meaning                                                                                                                |
|----------------------|---------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| enabled              | `false`                                           | Turn on LanceDB sidecar indexing and search blend                                                                      |
| backend              | `lancedb`                                         | Vector backend (only `lancedb` today)                                                                                  |
| index_path           | `.codeclone/memory/semantic_index.lance`          | Sidecar directory                                                                                                      |
| embedding_provider   | `diagnostic`                                      | `diagnostic` (hash vectors, not semantic quality), `fastembed` (local semantic-quality provider), `local_model`, `api` |
| embedding_model      | `null` (`BAAI/bge-small-en-v1.5` for `fastembed`) | Optional provider model name                                                                                           |
| embedding_cache_dir  | `.codeclone/memory/fastembed`                     | Local model cache used by `fastembed`                                                                                  |
| allow_model_download | `false`                                           | Permit `fastembed` to download a missing model instead of requiring a pre-populated cache                              |
| dimension            | `256` (`384` for `fastembed`)                     | Vector size; must match the provider model                                                                             |
| max_results          | `20`                                              | Cap for vector `k` and merged search ranking                                                                           |
| index_audit          | `true`                                            | Index bounded audit `summary` rows when audit DB exists                                                                |

Semantic-quality local search requires both the LanceDB sidecar and FastEmbed:
install `codeclone[semantic-local]` (or combine `semantic-lancedb` +
`semantic-fastembed`), set `embedding_provider = "fastembed"`, then run
`codeclone memory semantic rebuild` after enabling. `semantic-lancedb` alone can
build the sidecar with the diagnostic hash provider, which is deterministic but
not semantic-quality recall.

This is the exact accepted `[tool.codeclone]` key set from
`codeclone/config/spec.py` and `codeclone/config/pyproject_loader.py`; unknown
keys are contract errors.

!!! note "Pyproject keys vs CLI flags"
    The tables above list `[tool.codeclone]` keys, not CLI flag spellings.
    CLI flags may map to the same internal destination under a different name.
    Example: `coverage_xml` in `pyproject.toml` corresponds to CLI
    `--coverage FILE`. The same pattern applies to report outputs such as
    `html_out` ↔ `--html` and `json_out` ↔ `--json`.

    CLI-only flags (no `[tool.codeclone]` key; authoritative spelling in
    `tests/fixtures/contract_snapshots/cli_help.txt`):

    | CLI flag                         | Group         | Meaning                                                                            |
    |----------------------------------|---------------|------------------------------------------------------------------------------------|
    | `--changed-only`                 | Analysis      | Limit clone gating/summaries to git-selected files                                 |
    | `--diff-against GIT_REF`         | Analysis      | Resolve changed files from `git diff --name-only <REF>`; requires `--changed-only` |
    | `--paths-from-git-diff GIT_REF`  | Analysis      | Shorthand for `--changed-only` + git diff selection                                |
    | `--blast-radius FILE [FILE ...]` | Analysis      | Render structural blast radius for given files after analysis                      |
    | `--patch-verify`                 | Analysis      | Verify current patch against trusted clone baseline-relative budget                |
    | `--strictness LEVEL`             | Analysis      | `ci`, `strict`, or `relaxed`; valid only with `--patch-verify` (default: `ci`)     |
    | `--session-stats`                | Analysis      | Show workspace session status; read-only                                           |
    | `--audit`                        | Analysis      | Show local Controller audit trail; requires `audit_enabled=true`                   |
    | `--audit-json`                   | Analysis      | JSON audit footprint; implies `--audit`                                            |
    | `--cache-dir [FILE]`             | Analysis      | Legacy alias for `--cache-path`                                                    |
    | `--timestamped-report-paths`     | Reporting     | Append UTC timestamp to default report filenames                                   |
    | `--open-html-report`             | Output and UI | Open generated HTML in browser; requires `--html`                                  |
    | `--progress`                     | Output and UI | Force-enable progress output                                                       |
    | `--color`                        | Output and UI | Force-enable ANSI colors                                                           |

    Canonical help text, defaults, and exit-code epilog are locked by
    `tests/test_cli_help_snapshot.py` and `tests/test_cli_unit.py::test_cli_help_text_consistency`.

!!! warning "Metrics-mode conflicts are enforced"
    Metrics update/gating flags are runtime contracts, not hints. Combinations
    such as `skip_metrics=true` together with metrics gating or metrics
    baseline update flags are contract errors.

    Notes:

    - `skip_metrics=false*`: parser default is `false`, but runtime may auto-enable
      it when no metrics work is requested and no metrics baseline exists.
    - Report output keys default to `null`; bare CLI flags still write to the
      deterministic `.codeclone/report.*` paths listed above.

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
    - There is no user-facing knob to tune that model in the current `2.x` release
      line.

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

## Environment variable overrides

Single home for all `CODECLONE_*` environment variables. Other chapters link here
instead of duplicating tables.

**Truthy values** (where noted): `1`, `true`, `yes`, `on` (case-insensitive).
**Falsy values** (where noted): `0`, `false`, `no`, `off`.

### Precedence by subsystem

| Subsystem                        | Resolver                                         | Precedence when an env var is set                                                          |
|----------------------------------|--------------------------------------------------|--------------------------------------------------------------------------------------------|
| Main CLI scan                    | `resolve_config`                                 | CLI > pyproject > defaults; only `CODECLONE_DEBUG` applies from env                        |
| Engineering Memory               | `resolve_memory_config`                          | Documented env > `[tool.codeclone.memory]` / `[tool.codeclone.memory.semantic]` > defaults |
| Workspace intent registry        | `resolve_intent_registry_config`                 | Documented env > `[tool.codeclone]` registry keys > defaults                               |
| MCP workspace intent TTL / lease | `resolved_ttl_seconds`, `resolved_lease_seconds` | Explicit MCP tool parameter > env > built-in default                                       |
| Finish hygiene strict mode       | `_strict_finish_enabled`                         | Env only (no pyproject key)                                                                |
| Platform Observability           | `resolve_observability_config`                   | Env only; disabled by default, no pyproject table                                          |
| Corpus Analytics                 | `resolve_analytics_config`                       | `[tool.codeclone.analytics]` > built-in defaults; no env overrides in Slice 1              |
| Cursor / IDE hooks               | hook helpers                                     | Env > repo config file (where noted) > built-in default                                    |

There is no generic `CODECLONE_MEMORY__*` nested env convention. Each variable
name is flat and listed below.

### Diagnostics

| Variable          | Values      | Effect                                                                                                                               |
|-------------------|-------------|--------------------------------------------------------------------------------------------------------------------------------------|
| `CODECLONE_DEBUG` | `1` enables | Turns on CLI debug diagnostics (`codeclone/surfaces/cli/console.py`). Independent of analysis, gating, and `[tool.codeclone] debug`. |

### Platform Observability

Platform Observability is environment-only and disabled by default. It has no
`[tool.codeclone.observability]` table. See
[Platform Observability](26-platform-observability.md) for the data and trust
contracts.

### Corpus Analytics

Optional intent corpus clustering uses `[tool.codeclone.analytics]`. Install
`codeclone[analytics]` before running `codeclone analytics …`. Paths resolve
under the repository root. The historical audit source is inherited from the
top-level `[tool.codeclone].audit_path`; it is not duplicated in the analytics
table. `embedding_provider` currently accepts only `fastembed`, and
`default_cluster_selection_method` accepts `eom` or `leaf`. Full key list:
[Corpus Analytics](27-corpus-analytics.md#configuration).

Refs:

- `codeclone/config/analytics.py:resolve_analytics_config`
- `codeclone/config/pyproject_loader.py:load_pyproject_config`

### Platform Observability (environment)

| Variable                                        | Values         | Effect                                                              |
|-------------------------------------------------|----------------|---------------------------------------------------------------------|
| `CODECLONE_OBSERVABILITY_ENABLED`               | truthy / falsy | Enable local operation/span instrumentation.                        |
| `CODECLONE_OBSERVABILITY_FORCE`                 | truthy / falsy | Lift the CI collection guard; does not enable collection by itself. |
| `CODECLONE_OBSERVABILITY_PROFILE`               | truthy / falsy | Capture process metrics; requires `codeclone[perf]`.                |
| `CODECLONE_OBSERVABILITY_PERSIST`               | truthy / falsy | Persist completed operations; default true when enabled.            |
| `CODECLONE_OBSERVABILITY_CAPTURE_PAYLOAD_SIZES` | truthy / falsy | Capture bounded size/token estimates; default true.                 |
| `CODECLONE_OBSERVABILITY_PAYLOAD_SNAPSHOT`      | reserved       | Rejected; raw payload snapshots are unsupported.                    |
| `CODECLONE_OBSERVABILITY_CORRELATION_ID`        | internal ID    | Worker handoff for cross-process correlation; set by CodeClone.     |
| `CODECLONE_OBSERVABILITY_PARENT_OPERATION_ID`   | internal ID    | Worker handoff for the parent operation; set by CodeClone.          |

The internal correlation variables are launcher/worker protocol, not operator
tuning knobs.

### Engineering Memory

Overrides `[tool.codeclone.memory]` and `[tool.codeclone.memory.semantic]` for the
listed field only. Paths resolve under the repository root like pyproject paths.

| Variable                                         | Values                                          | Overrides                              | Effect                                                                                    |
|--------------------------------------------------|-------------------------------------------------|----------------------------------------|-------------------------------------------------------------------------------------------|
| `CODECLONE_MEMORY_DB_PATH`                       | repo-relative or absolute path under root       | `memory.db_path`                       | SQLite Engineering Memory store location                                                  |
| `CODECLONE_PROJECTION_REBUILD_POLICY`            | `off`, `enqueue_when_stale`                     | `memory.projection_rebuild_policy`     | When accepted MCP finish may enqueue async trajectory/semantic/Experience projection jobs |
| `CODECLONE_MEMORY_SEMANTIC_ENABLED`              | `true` / `false`                                | `memory.semantic.enabled`              | Turn semantic index sidecar on or off                                                     |
| `CODECLONE_MEMORY_SEMANTIC_EMBEDDING_PROVIDER`   | `diagnostic`, `fastembed`, `local_model`, `api` | `memory.semantic.embedding_provider`   | Embedding backend for semantic rebuild/search                                             |
| `CODECLONE_MEMORY_SEMANTIC_EMBEDDING_MODEL`      | model name string                               | `memory.semantic.embedding_model`      | Provider model id (for example FastEmbed model name)                                      |
| `CODECLONE_MEMORY_SEMANTIC_EMBEDDING_CACHE_DIR`  | path                                            | `memory.semantic.embedding_cache_dir`  | Local ONNX/model cache directory for FastEmbed                                            |
| `CODECLONE_MEMORY_SEMANTIC_ALLOW_MODEL_DOWNLOAD` | `true` / `false`                                | `memory.semantic.allow_model_download` | When `false`, FastEmbed requires a pre-populated cache                                    |
| `CODECLONE_MEMORY_SEMANTIC_INDEX_PATH`           | path                                            | `memory.semantic.index_path`           | LanceDB semantic sidecar directory                                                        |

Memory keys without a documented env override (for example
`projection_rebuild_spawn_worker`) are pyproject-only.

Refs: `codeclone/config/memory.py`, `codeclone/config/memory_defaults.py`.

### Workspace intent registry

Overrides `[tool.codeclone]` registry keys. Used by MCP workspace coordination
and local hook gate reads.

| Variable                                   | Values                                  | Overrides                        | Effect                                                                 |
|--------------------------------------------|-----------------------------------------|----------------------------------|------------------------------------------------------------------------|
| `CODECLONE_INTENT_REGISTRY_BACKEND`        | `file`, `sqlite`                        | `intent_registry_backend`        | File-per-intent JSON under `.codeclone/intents/` vs SQLite WAL backend |
| `CODECLONE_INTENT_REGISTRY_PATH`           | `.sqlite3` / `.db` path under repo root | `intent_registry_path`           | SQLite database path when backend is `sqlite`                          |
| `CODECLONE_INTENT_REGISTRY_RETENTION_DAYS` | integer `1`–`14` (open source)          | `intent_registry_retention_days` | Closed-row retention for SQLite backend purge                          |

Refs: `codeclone/config/intent_registry.py`.

### MCP session and change-control hygiene

| Variable                         | Values         | Applies when                                                                         | Effect                                                                                                                                    |
|----------------------------------|----------------|--------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| `CODECLONE_INTENT_TTL_SECONDS`   | `60`–`86400`   | `start_controlled_change` / workspace registry write when tool `ttl_seconds` omitted | Hard maximum lifetime of a workspace intent record (default `3600`)                                                                       |
| `CODECLONE_INTENT_LEASE_SECONDS` | `60`–`600`     | Workspace registry lease renewal when tool `lease_seconds` omitted                   | Ownership freshness window renewed by active MCP use (default `300`)                                                                      |
| `CODECLONE_STRICT_FINISH`        | truthy / falsy | `finish_controlled_change` hygiene                                                   | When truthy, unattributed out-of-scope dirty may set `finish_block_reason: own_unscoped_dirty` and block finish; default is advisory only |

Explicit `ttl_seconds` / `lease_seconds` on MCP tools take precedence over the
matching env var.

Refs: `codeclone/surfaces/mcp/_workspace_intents.py`,
`codeclone/surfaces/mcp/_workspace_hygiene.py`.

### MCP HTTP authentication

| Variable                   | Values                        | Effect                                                                                                                                                                                      |
|----------------------------|-------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `CODECLONE_MCP_AUTH_TOKEN` | string, minimum 32 characters | Bearer token for `streamable-http` transport. Required for authenticated remote HTTP; validated with constant-time compare. Without it, HTTP MCP is an unauthenticated local-trust surface. |

Refs: `codeclone/surfaces/mcp/auth.py`, [21-security-model.md](21-security-model.md).

### Workspace edit gate (hooks)

Read by `codeclone/workspace_intent/gate.py` for Cursor/IDE pre-edit enforcement.

| Variable                               | Values                | Default when unset               | Effect                                                                                         |
|----------------------------------------|-----------------------|----------------------------------|------------------------------------------------------------------------------------------------|
| `CODECLONE_HOOK_AUTHORIZE_FOREIGN`     | truthy / falsy        | authorize foreign active intents | When `0`/`false`/`no`/`off`, a live foreign active intent does not authorize local hook writes |
| `CODECLONE_HOOK_OWN_AGENT_PID`         | integer PID           | hook argument only               | Limits stop-hook cleanup to recoverable intents owned by this process                          |
| `CODECLONE_HOOK_OWN_AGENT_START_EPOCH` | integer epoch seconds | hook argument only               | Pairs with own-agent PID for recoverable intent matching                                       |

### Cursor plugin hooks

| Variable                        | Values           | Precedence                                              | Effect                                                                                                                        |
|---------------------------------|------------------|---------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| `CODECLONE_HOOKS_ENFORCE_SCOPE` | `python`, `repo` | env > `.cursor/codeclone-hooks.json` > default `python` | `python`: gate `.py`/`.pyi` edits and matching shell commands. `repo`: gate any path under workspace root including `.git/**` |

Refs: `plugins/cursor-codeclone/hooks/_hook_io.py`, [integrations/cursor-plugin.md](integrations/cursor-plugin.md).

### IDE and MCP launcher passthrough

Set by VS Code, Claude Desktop, Claude Code, Codex, and Cursor launchers — not
usually edited in `pyproject.toml`. Launchers forward variables prefixed with
`CODECLONE_` to the child `codeclone-mcp` process.

| Variable                          | Values              | Effect                                                                                                                        |
|-----------------------------------|---------------------|-------------------------------------------------------------------------------------------------------------------------------|
| `CODECLONE_WORKSPACE_ROOT`        | absolute path       | Preferred repository root for launcher workspace discovery and MCP child env when cwd/PWD disagree with the trusted workspace |
| `CODECLONE_MCP_COMMAND`           | command path        | Claude Desktop bundle: override MCP server executable                                                                         |
| `CODECLONE_MCP_ARGS_JSON`         | JSON string array   | Claude Desktop bundle: extra launcher argv (stdio transport locked by IDE clients)                                            |
| `CODECLONE_MCP_SHUTDOWN_GRACE_MS` | positive integer ms | Grace period before SIGTERM when stopping MCP child (default `5000`)                                                          |
| `CODECLONE_MCP_KILL_GRACE_MS`     | positive integer ms | Grace period before SIGKILL after SIGTERM (default `2000`)                                                                    |

Refs: `plugins/codeclone/scripts/launch_mcp.py`,
`extensions/vscode-codeclone/src/support.js`,
`extensions/claude-desktop-codeclone/src/launcher.js`.

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
  deterministic default path under `.codeclone/`.
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

- [11-cli.md](11-cli.md)
- [16-metrics-and-quality-gates.md](16-metrics-and-quality-gates.md)
- [13-engineering-memory/bootstrap-and-config.md](13-engineering-memory/bootstrap-and-config.md) — memory pyproject
  tables (env overrides live here)
