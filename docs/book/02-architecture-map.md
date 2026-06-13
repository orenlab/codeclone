<!-- doc-scope: AUTHORITATIVE MODULE TABLE — maps source paths to chapters/tests.
     owns: module-to-chapter routing table.
     does-not-own: narrative architecture (→ ../guide/explanation/how-it-works.md), module internals.
     rule: this is the MAP. guide/explanation/how-it-works.md is the NARRATIVE. Do not merge. -->

# 02. Architecture Map

## Purpose

Document the current module boundaries and ownership in CodeClone `2.1.x`.

## Public surface

Main ownership layers:

- CLI entry and UX orchestration
- Config parsing and pyproject resolution
- Core runtime pipeline
- Analysis and clone grouping
- Metrics and findings
- Baseline/cache persistence contracts
- Canonical report document and deterministic projections
- HTML render-only surface
- Read-only MCP surface with structural change control and claim validation
- IDE/client surfaces over MCP

## Data model

| Layer                   | Modules                                                                                                                       | Responsibility                                                                                                                                                                                                                                                                                                                 |
|-------------------------|-------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Entry                   | `codeclone/main.py`                                                                                                           | Public CLI entrypoint only                                                                                                                                                                                                                                                                                                     |
| CLI surface             | `codeclone/surfaces/cli/*`, `codeclone/ui_messages/*`                                                                         | Parse args, resolve runtime mode, print summaries, write outputs, route exits                                                                                                                                                                                                                                                  |
| Report copy             | `codeclone/report/messages/*`                                                                                                 | Glossary, suggestions, explainability, overview, security, chrome, text/markdown/sarif projections, gate prefixes                                                                                                                                                                                                              |
| Config                  | `codeclone/config/*`                                                                                                          | Option specs, parser construction, pyproject loading, CLI > pyproject > defaults merge                                                                                                                                                                                                                                         |
| Core runtime            | `codeclone/core/*`                                                                                                            | Bootstrap, discovery, worker processing, project metrics, report/gate integration                                                                                                                                                                                                                                              |
| Analysis                | `codeclone/analysis/*`, `codeclone/blocks/*`, `codeclone/paths/*`, `codeclone/qualnames/*`                                    | Parse source, normalize AST/CFG facts, extract units, prepare deterministic analysis inputs; includes shared blast-radius graph core (`analysis/blast_radius.py`)                                                                                                                                                              |
| Findings                | `codeclone/findings/clones/*`, `codeclone/findings/structural/*`                                                              | Clone grouping and structural finding derivation                                                                                                                                                                                                                                                                               |
| Metrics                 | `codeclone/metrics/*`                                                                                                         | Complexity, coupling, cohesion, dependencies, dead code, health, adoption, coverage join, API surface                                                                                                                                                                                                                          |
| Contracts/domain        | `codeclone/contracts/*`, `codeclone/models.py`, `codeclone/domain/*`                                                          | Version constants, enums, typed exceptions, shared models, domain taxonomies                                                                                                                                                                                                                                                   |
| Persistence             | `codeclone/baseline/*`, `codeclone/cache/*`                                                                                   | Trusted comparison state and optimization-only cache contracts                                                                                                                                                                                                                                                                 |
| Canonical report        | `codeclone/report/document/*`, `codeclone/report/gates/*`, `codeclone/report/*.py`                                            | Canonical report payload, derived projections, explainability, suggestions, gate reasons                                                                                                                                                                                                                                       |
| Deterministic renderers | `codeclone/report/renderers/*`                                                                                                | Text/Markdown/SARIF/JSON projections over the canonical report                                                                                                                                                                                                                                                                 |
| HTML render layer       | `codeclone/report/html/*`                                                                                                     | Render-only HTML view over canonical report/meta facts                                                                                                                                                                                                                                                                         |
| MCP surface             | `codeclone/surfaces/mcp/*`, `codeclone/surfaces/mcp/messages/*`                                                               | Read-only MCP tools/resources, change-control projections, Engineering Memory retrieval/governance, dev-only Platform Observability slices, and centralized agent-facing copy                                                                                                                                                |
| Engineering Memory      | `codeclone/memory/*`, `codeclone/config/memory*.py`                                                                           | Local SQLite store, scoped retrieval, semantic sidecar, trajectory + Patch Trail projection, Experience distillation, coalesced rebuild jobs, staleness, governance, and CLI/MCP surfaces over deterministic report/git/doc/audit facts                                                                                       |
| Platform Observability  | `codeclone/observability/*`                                                                                                   | Opt-in operation/span telemetry, local SQLite store, bounded MCP slicer, and CLI JSON/HTML diagnostics; never analysis truth or a gate input                                                                                                                                                                                   |
| Controller insights     | `codeclone/controller_insights/*`                                                                                             | Shared session-stats and audit-trail payloads for CLI `--session-stats` / `--audit` and IDE-only MCP `get_workspace_session_stats` / `get_controller_audit_trail`                                                                                                                                                              |
| Audit trail             | `codeclone/audit/*`                                                                                                           | Optional controller event and MCP payload footprint recording under `.codeclone/db/` when enabled                                                                                                                                                                                                                              |
| Client surfaces         | `extensions/vscode-codeclone/*`, `extensions/claude-desktop-codeclone/*`, `plugins/codeclone/*`, `plugins/cursor-codeclone/*`, `plugins/claude-code-codeclone/*` | Native clients/install surfaces over `codeclone-mcp`                                                                                                                                                                                                                                                     |

Refs:

- `codeclone/main.py:main`
- `codeclone/surfaces/cli/workflow.py:_main_impl`
- `codeclone/core/pipeline.py:analyze`
- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/report/html/assemble.py:build_html_report`
- `codeclone/surfaces/mcp/server.py:build_mcp_server`

## Contracts

- Core produces facts; renderers present facts.
- `codeclone/report/document/*` is the canonical report source of truth.
- HTML, Markdown, SARIF, text, and MCP are projections over the same canonical report semantics.
- Baseline and cache are persistence contracts, not analysis truth.
- Cache is optimization-only and fail-open.
- MCP is read-only and must not create a second analysis truth path. Change
  control and claim guard are projections over stored run/report semantics, not
  new analyzers.
- VS Code, Claude Desktop, Claude Code, Codex, and Cursor surfaces are clients
  over MCP, not second analyzers.

Refs:

- `codeclone/report/document/builder.py:build_report_document`
- `codeclone/report/renderers/text.py:render_text_report_document`
- `codeclone/report/renderers/markdown.py:render_markdown_report_document`
- `codeclone/report/renderers/sarif.py:render_sarif_report_document`
- `codeclone/report/html/assemble.py:build_html_report`
- `codeclone/baseline/clone_baseline.py:Baseline.load`
- `codeclone/baseline/metrics_baseline.py:MetricsBaseline.load`
- `codeclone/cache/store.py:Cache.load`

## Invariants (MUST)

- Report serialization is deterministic and schema-versioned.
- UI is render-only and must not invent gating semantics.
- Status enums remain domain-owned in baseline/metrics-baseline/cache/contracts modules.
- `codeclone/main.py` stays thin; orchestration lives in `codeclone/surfaces/cli/*`.

Refs:

- `codeclone/report/document/integrity.py:_build_integrity_payload`
- `codeclone/report/document/inventory.py:_build_inventory_payload`
- `codeclone/baseline/trust.py:BaselineStatus`
- `codeclone/baseline/_metrics_baseline_contract.py:MetricsBaselineStatus`
- `codeclone/cache/versioning.py:CacheStatus`
- `codeclone/contracts/__init__.py:ExitCode`

## Failure modes

| Condition                                        | Layer                                                          |
|--------------------------------------------------|----------------------------------------------------------------|
| Invalid CLI args / invalid output path           | CLI surface (`codeclone/config/*`, `codeclone/surfaces/cli/*`) |
| Baseline schema/integrity mismatch               | Baseline contract layer                                        |
| Metrics baseline schema/integrity mismatch       | Metrics-baseline contract layer                                |
| Cache corruption/version mismatch                | Cache contract layer (fail-open)                               |
| HTML snippet read failure                        | HTML render layer fallback snippet                             |
| MCP invalid request / invalid root / unknown run | MCP surface                                                    |

## Determinism / canonicalization

- File iteration and grouping order are explicit sorts.
- Canonical report integrity excludes non-canonical `derived` payload.
- Baseline and cache hashes/signatures use canonical JSON.

Refs:

- `codeclone/scanner/__init__.py:iter_py_files`
- `codeclone/report/document/integrity.py:_build_integrity_payload`
- `codeclone/baseline/trust.py:_compute_payload_sha256`
- `codeclone/cache/integrity.py:canonical_json`

## Locked by tests

- `tests/test_architecture.py::test_architecture_layer_violations`
- `tests/test_report.py::test_report_json_compact_v21_contract`
- `tests/test_report_contract_coverage.py::test_report_document_rich_invariants_and_renderers`
- `tests/test_html_report.py::test_html_report_uses_core_block_group_facts`
- `tests/test_cache.py::test_cache_v13_uses_relpaths_when_root_set`
- `tests/test_mcp_service.py::test_mcp_service_analyze_repository_registers_latest_run`

## Non-guarantees

- Internal file splits may evolve in `2.1.x` if public contracts are preserved.
- Package markers and internal helper placement are not contract by themselves.

## Chapter map

| Topic                                 | Primary chapters                                                                                                 |
|---------------------------------------|------------------------------------------------------------------------------------------------------------------|
| CLI behavior and failure routing      | [09-exit-codes.md](09-exit-codes.md), [11-cli.md](11-cli.md)                                                     |
| Config precedence and defaults        | [10-config-and-defaults.md](10-config-and-defaults.md)                                                           |
| Core processing pipeline              | [03-core-pipeline.md](03-core-pipeline.md)                                                                       |
| Clone baseline trust/compat/integrity | [07-baseline.md](07-baseline.md)                                                                                 |
| Cache trust and fail-open behavior    | [08-cache.md](08-cache.md)                                                                                       |
| Report schema and provenance          | [05-report.md](05-report.md), [06-html-render.md](06-html-render.md)                                             |
| MCP agent surface                     | [25-mcp-interface/index.md](25-mcp-interface/index.md), [14-claim-guard.md](14-claim-guard.md)                               |
| Engineering Memory evidence layers    | [13-engineering-memory/index.md](13-engineering-memory/index.md), [13-engineering-memory/trajectory-quality-and-passport.md](13-engineering-memory/trajectory-quality-and-passport.md), [13-engineering-memory/experience-layer.md](13-engineering-memory/experience-layer.md) |
| Platform runtime diagnostics          | [26-platform-observability.md](26-platform-observability.md)                                                               |
| Health score model                    | [15-health-score.md](15-health-score.md)                                                                         |
| Metrics gates and metrics baseline    | [16-metrics-and-quality-gates.md](16-metrics-and-quality-gates.md)                                               |
| Dead-code liveness policy             | [17-dead-code-contract.md](17-dead-code-contract.md)                                                             |
| Determinism and versioning policy     | [22-determinism.md](22-determinism.md), [24-compatibility-and-versioning.md](24-compatibility-and-versioning.md) |
