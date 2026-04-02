# 01. Architecture Map

## Purpose

Document current module boundaries and ownership in CodeClone v2.x.

## Public surface

Main ownership layers:

- Core detection pipeline: `scanner` -> `extractor` -> `cfg/normalize/blocks` -> `grouping`.
- Quality metrics pipeline: complexity/coupling/cohesion/dependencies/dead-code/health.
- Contracts and persistence: baseline, metrics baseline, cache, exit semantics.
- Report model and projections: canonical JSON + deterministic TXT/Markdown/SARIF + explainability facts.
- MCP agent surface: read-only server layer over the same pipeline/report contracts.
- Render layer: HTML rendering and template assets.

## Data model

| Layer                 | Modules                                                                                                                                                                                            | Responsibility                                                                                  |
|-----------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| Contracts             | `codeclone/contracts.py`, `codeclone/errors.py`                                                                                                                                                    | Shared schema versions, URLs, exit-code enum, typed exceptions                                  |
| Domain models         | `codeclone/models.py`, `codeclone/domain/*.py`                                                                                                                                                     | Typed dataclasses/enums plus centralized finding/scope/severity taxonomies                      |
| Discovery + parsing   | `codeclone/scanner.py`, `codeclone/extractor.py`                                                                                                                                                   | Enumerate files, parse AST, extract function/block/segment units                                |
| Structural analysis   | `codeclone/cfg.py`, `codeclone/normalize.py`, `codeclone/fingerprint.py`, `codeclone/blocks.py`                                                                                                    | CFG, normalization, statement hashes, block/segment windows                                     |
| Grouping              | `codeclone/grouping.py`                                                                                                                                                                            | Build function/block/segment groups                                                             |
| Metrics               | `codeclone/metrics/*`                                                                                                                                                                              | Compute complexity/coupling/cohesion/dependency/dead-code/health signals                        |
| Report core           | `codeclone/report/*`, `codeclone/_cli_meta.py`                                                                                                                                                     | Canonical report building, deterministic projections, explainability facts, and shared metadata |
| Persistence           | `codeclone/baseline.py`, `codeclone/metrics_baseline.py`, `codeclone/cache.py`                                                                                                                     | Baseline/cache trust/compat/integrity and atomic persistence                                    |
| Runtime orchestration | `codeclone/pipeline.py`, `codeclone/cli.py`, `codeclone/_cli_args.py`, `codeclone/_cli_paths.py`, `codeclone/_cli_summary.py`, `codeclone/_cli_config.py`, `codeclone/ui_messages.py`              | CLI UX, stage orchestration, status handling, outputs, error markers                            |
| MCP agent interface   | `codeclone/mcp_service.py`, `codeclone/mcp_server.py`                                                                                                                                              | Read-only MCP tools/resources over canonical analysis and report layers                         |
| Rendering             | `codeclone/html_report.py`, `codeclone/_html_report/*`, `codeclone/_html_badges.py`, `codeclone/_html_js.py`, `codeclone/_html_escape.py`, `codeclone/_html_snippets.py`, `codeclone/templates.py` | HTML-only view layer over report data                                                           |

Refs:

- `codeclone/pipeline.py`
- `codeclone/cli.py:_main_impl`

## Contracts

- Core analysis modules do not depend on render/UI modules.
- HTML renderer receives already-computed report data/facts and does not
  recompute detection semantics.
- MCP layer reuses current pipeline/report semantics and must not introduce a
  separate analysis truth path.
- MCP may ship task-specific slim projections (for example, summary-only metrics
  or inventory counts) as long as canonical report data remains the source of
  truth and richer detail stays reachable through dedicated tools/sections.
- The same rule applies to bounded semantic routing tools such as
  `help(topic=...)`: they explain contract meaning and route agents to the
  safest next step, but they do not introduce a second documentation or truth
  model.
- The same rule applies to summary cache convenience fields such as
  `freshness` and to production-first triage projections built from
  canonical hotlists/suggestions.
- MCP finding lists may also expose short run/finding ids and slimmer relative
  location projections, while keeping `get_finding(detail_level="full")` as the
  richer per-finding inspection path.
- Baseline, metrics baseline, and cache are validated before being trusted.

Refs:

- `codeclone/report/json_contract.py:build_report_document`
- `codeclone/html_report.py:build_html_report`
- `codeclone/baseline.py:Baseline.load`
- `codeclone/metrics_baseline.py:MetricsBaseline.load`
- `codeclone/cache.py:Cache.load`

## Invariants (MUST)

- Report serialization is deterministic and schema-versioned.
- UI is render-only and must not change gating semantics.
- Status enums remain domain-owned in baseline/metrics-baseline/cache modules.

Refs:

- `codeclone/report/json_contract.py:build_report_document`
- `codeclone/report/explain.py:build_block_group_facts`
- `codeclone/baseline.py:BaselineStatus`
- `codeclone/metrics_baseline.py:MetricsBaselineStatus`
- `codeclone/cache.py:CacheStatus`

## Failure modes

| Condition                                  | Layer                                             |
|--------------------------------------------|---------------------------------------------------|
| Invalid CLI args / invalid output path     | Runtime orchestration (`_cli_args`, `_cli_paths`) |
| Baseline schema/integrity mismatch         | Baseline contract layer                           |
| Metrics baseline schema/integrity mismatch | Metrics baseline contract layer                   |
| Cache corruption/version mismatch          | Cache contract layer (fail-open)                  |
| HTML snippet read failure                  | Render layer fallback snippet                     |

## Determinism / canonicalization

- File iteration and group key ordering are explicit sorts.
- Report serializer uses fixed record layouts and sorted keys.

Refs:

- `codeclone/scanner.py:iter_py_files`
- `codeclone/report/json_contract.py:build_report_document`

## Locked by tests

- `tests/test_report.py::test_report_json_compact_v21_contract`
- `tests/test_html_report.py::test_html_report_uses_core_block_group_facts`
- `tests/test_cache.py::test_cache_v13_uses_relpaths_when_root_set`
- `tests/test_cli_unit.py::test_argument_parser_contract_error_marker_for_invalid_args`
- `tests/test_architecture.py::test_architecture_layer_violations`

## Non-guarantees

- Internal module split may evolve in v2.x if public contracts are preserved.
- Import tree acyclicity is policy and test-enforced where explicitly asserted.

## Chapter map

| Topic                                 | Primary chapters                                                                                                 |
|---------------------------------------|------------------------------------------------------------------------------------------------------------------|
| CLI behavior and failure routing      | [03-contracts-exit-codes.md](03-contracts-exit-codes.md), [09-cli.md](09-cli.md)                                 |
| Config precedence and defaults        | [04-config-and-defaults.md](04-config-and-defaults.md)                                                           |
| Core processing pipeline              | [05-core-pipeline.md](05-core-pipeline.md)                                                                       |
| Clone baseline trust/compat/integrity | [06-baseline.md](06-baseline.md)                                                                                 |
| Cache trust and fail-open behavior    | [07-cache.md](07-cache.md)                                                                                       |
| Report schema and provenance          | [08-report.md](08-report.md), [10-html-render.md](10-html-render.md)                                             |
| MCP agent surface                     | [20-mcp-interface.md](20-mcp-interface.md)                                                                       |
| Metrics gates and metrics baseline    | [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)                                               |
| Dead-code liveness policy             | [16-dead-code-contract.md](16-dead-code-contract.md)                                                             |
| Suggestions and clone typing          | [17-suggestions-and-clone-typing.md](17-suggestions-and-clone-typing.md)                                         |
| Determinism and versioning policy     | [12-determinism.md](12-determinism.md), [14-compatibility-and-versioning.md](14-compatibility-and-versioning.md) |
