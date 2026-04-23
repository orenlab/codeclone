# CodeClone Docs

This site is built with MkDocs and published to
[orenlab.github.io/codeclone](https://orenlab.github.io/codeclone/).

!!! note "Version Notice"
This site currently documents the in-development `v2.0.x` line from `main`.
For the latest stable CodeClone documentation (`v1.4.4`), see the
[`v1.4.4` README](https://github.com/orenlab/codeclone/blob/v1.4.4/README.md)
and the
[`v1.4.4` docs tree](https://github.com/orenlab/codeclone/tree/v1.4.4/docs).

It has two documentation layers:

- [Contracts Book](book/README.md): **contract-first** documentation. This is the canonical
  source for **schemas**, **statuses**, **exit codes**, **trust model**, and
  **determinism guarantees**. Everything here is derived from code + locked
  tests.
- [Architecture Narrative](architecture.md), [CFG Semantics](cfg.md):
  **deep-dive narrative** docs (architecture and CFG semantics). These may
  include rationale and design intent, but must not contradict the contract
  book.

The published site also exposes a live sample report generated from the current
repository build:

- [Examples / Sample Report](examples/report.md)

## Start Here

- [Contracts and guarantees](book/00-intro.md)
- [Architecture map (components + ownership)](book/01-architecture-map.md)
- [Terminology](book/02-terminology.md)

## Core Contracts

- [Exit codes and failure policy](book/03-contracts-exit-codes.md)
- [Config and defaults](book/04-config-and-defaults.md)
- [Core pipeline and invariants](book/05-core-pipeline.md)
- [Baseline contract (schema v2.1)](book/06-baseline.md)
- [Cache contract (schema v2.5)](book/07-cache.md)
- [Report contract (schema v2.9)](book/08-report.md)

## Interfaces

- [CLI behavior, modes, and UX](book/09-cli.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [VS Code extension contract](book/21-vscode-extension.md)
- [Claude Desktop bundle contract](book/22-claude-desktop-bundle.md)
- [Codex plugin contract](book/23-codex-plugin.md)
- [HTML report rendering contract](book/10-html-render.md)

The VS Code extension docs cover the native IDE surface for canonical review
facts, including optional `Coverage Join` overview data and version-gated MCP
help topics when the connected server exposes them.

## System Properties

- [Security model and threat boundaries](book/11-security-model.md)
- [Determinism policy](book/12-determinism.md)
- [Tests as specification](book/13-testing-as-spec.md)
- [Compatibility and versioning rules](book/14-compatibility-and-versioning.md)

## Quality Contracts

- [Health Score model and evolution policy](book/15-health-score.md)
- [Metrics mode and quality gates](book/15-metrics-and-quality-gates.md)
- [Dead-code contract and test-boundary policy](book/16-dead-code-contract.md)
- [Suggestions and clone typing contract](book/17-suggestions-and-clone-typing.md)
- [Reproducible Docker benchmarking](book/18-benchmarking.md)
- [Inline suppressions contract](book/19-inline-suppressions.md)

## Deep Dives

- [Architecture narrative](architecture.md)
- [CFG design and semantics](cfg.md)
- [MCP integration for AI agents and clients](mcp.md)
- [VS Code extension usage guide](vscode-extension.md)
- [Claude Desktop bundle usage guide](claude-desktop-bundle.md)
- [Codex plugin usage guide](codex-plugin.md)
- [Privacy Policy](privacy-policy.md)
- [Terms of Use](terms-of-use.md)
- [SARIF integration for IDE/code-scanning use](sarif.md)
- [Docs publishing and Pages workflow](publishing.md)

## Reference Appendices

- [Status enums and typed contracts](book/appendix/a-status-enums.md)
- [Schema layouts (baseline/cache/report)](book/appendix/b-schema-layouts.md)
- [Error catalog (contract vs internal)](book/appendix/c-error-catalog.md)

## Local Preview

Build the docs site with MkDocs, then generate the sample report into the built
site:

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict
uv run python scripts/build_docs_example_report.py --output-dir site/examples/report/live
```

GitHub Pages publishing is handled by
[`docs.yml`](https://github.com/orenlab/codeclone/blob/main/.github/workflows/docs.yml)
via a custom Actions workflow.
