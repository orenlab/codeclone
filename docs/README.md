# CodeClone Docs

> Structural Change Controller for AI-assisted Python development —
> deterministic, baseline-aware, built for CI and AI agents.

CodeClone runs one deterministic analysis pipeline and emits a canonical JSON
report. Every surface — CLI, HTML, MCP, IDE — is a projection of that report.
Humans and AI agents operate on the same structural facts.

The v2.1 change controller starts before the first edit: an agent declares what
it intends to change, CodeClone maps the structural blast radius, verifies the
patch against the declared boundary, and generates an auditable review receipt.

!!! note "Licensing"
    Source code: MPL-2.0. Documentation and docs-site content: MIT.

---

## Getting Started

| Goal                  | Start here                                   |
|-----------------------|----------------------------------------------|
| First install and run | [Getting started](getting-started.md)        |
| Understand the model  | [Contracts and guarantees](book/00-intro.md) |
| Terminology lookup    | [Terminology](book/02-terminology.md)        |

## CI and Gating

| Goal                          | Start here                                                |
|-------------------------------|-----------------------------------------------------------|
| Baseline-aware CI             | [Getting started: CI setup](getting-started.md#ci-setup)  |
| Exit codes and failure policy | [Exit codes](book/03-contracts-exit-codes.md)             |
| Quality gates and metrics     | [Metrics and gates](book/15-metrics-and-quality-gates.md) |
| Baseline contract             | [Baseline](book/06-baseline.md)                           |

## AI Agent Governance

| Goal                               | Start here                                                              |
|------------------------------------|-------------------------------------------------------------------------|
| Change controller workflow         | [Structural Change Controller](book/24-structural-change-controller.md) |
| Engineering Memory (scope context) | [Engineering Memory](book/26-engineering-memory.md)                     |
| MCP interface contract             | [MCP interface](book/20-mcp-interface.md)                               |
| MCP usage guide                    | [MCP guide](mcp.md)                                                     |

## IDE and Agent Clients

| Surface               | Usage guide                       | Contract                                     |
|-----------------------|-----------------------------------|----------------------------------------------|
| VS Code extension     | [Guide](vscode-extension.md)      | [Contract](book/21-vscode-extension.md)      |
| Claude Desktop bundle | [Guide](claude-desktop-bundle.md) | [Contract](book/22-claude-desktop-bundle.md) |
| Codex plugin          | [Guide](codex-plugin.md)          | [Contract](book/23-codex-plugin.md)          |
| Cursor plugin         | [Guide](cursor-plugin.md)         | [Contract](book/25-cursor-plugin.md)         |

## Reports

| Goal                    | Start here                            |
|-------------------------|---------------------------------------|
| Report model and schema | [Report contract](book/08-report.md)  |
| HTML rendering          | [HTML render](book/10-html-render.md) |
| Live sample             | [Sample report](examples/report.md)   |

---

## Contracts Book

Contract-first documentation derived from code and locked tests.

### Core Contracts

- [Exit codes and failure policy](book/03-contracts-exit-codes.md)
- [Config and defaults](book/04-config-and-defaults.md)
- [Core pipeline and invariants](book/05-core-pipeline.md)
- [Baseline contract (schema v2.1)](book/06-baseline.md)
- [Cache contract (schema v2.8)](book/07-cache.md)
- [Report contract (schema v2.11)](book/08-report.md)

### Change Controller

- [Structural Change Controller](book/24-structural-change-controller.md)
- [Engineering Memory](book/26-engineering-memory.md)

### Interfaces

- [CLI behavior, modes, and UX](book/09-cli.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [VS Code extension contract](book/21-vscode-extension.md)
- [Claude Desktop bundle contract](book/22-claude-desktop-bundle.md)
- [Codex plugin contract](book/23-codex-plugin.md)
- [Cursor plugin contract](book/25-cursor-plugin.md)
- [Claim Guard](book/28-claim-guard.md)
- [HTML report rendering contract](book/10-html-render.md)

### System Properties

- [Security model and threat boundaries](book/11-security-model.md)
- [Determinism policy](book/12-determinism.md)
- [Tests as specification](book/13-testing-as-spec.md)
- [Compatibility and versioning rules](book/14-compatibility-and-versioning.md)

### Quality Contracts

- [Health Score model and evolution policy](book/15-health-score.md)
- [Metrics mode and quality gates](book/15-metrics-and-quality-gates.md)
- [Dead-code contract and test-boundary policy](book/16-dead-code-contract.md)
- [Suggestions and clone typing contract](book/17-suggestions-and-clone-typing.md)
- [Reproducible Docker benchmarking](book/18-benchmarking.md)
- [Inline suppressions contract](book/19-inline-suppressions.md)

---

## Deep Dives

- [Architecture narrative](architecture.md)
- [CFG design and semantics](cfg.md)
- [MCP integration guide](mcp.md)
- [VS Code extension usage](vscode-extension.md)
- [Claude Desktop bundle usage](claude-desktop-bundle.md)
- [Codex plugin usage](codex-plugin.md)
- [Cursor plugin usage](cursor-plugin.md)
- [SARIF integration](sarif.md)

### Operational

- [Privacy Policy](privacy-policy.md)
- [Terms of Use](terms-of-use.md)
- [Docs publishing and Pages workflow](publishing.md)

---

## Reference Appendices

- [Status enums and typed contracts](book/appendix/a-status-enums.md)
- [Schema layouts (baseline/cache/report)](book/appendix/b-schema-layouts.md)
- [Error catalog (contract vs internal)](book/appendix/c-error-catalog.md)

---

## Local Preview

```bash
# Build the site
uv run --with mkdocs --with mkdocs-material mkdocs build --strict

# Build with live sample report
uv run --with mkdocs --with mkdocs-material mkdocs build --strict
uv run python scripts/build_docs_example_report.py --output-dir site/examples/report/live
```

!!! note "Generated output"
    `site/` is generated output used for local preview and GitHub Pages publishing.
    It is not committed to git.
