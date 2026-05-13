# CodeClone Docs

> Deterministic structural review for Python codebases.
> One canonical analysis across CI, HTML reports, IDEs, and AI agents.

CodeClone is a structural review layer for Python focused on deterministic
analysis, baseline-aware governance, and review surfaces for both humans and
AI-assisted workflows.

This documentation site has two complementary layers:

- **Contracts Book** — canonical behavioral contracts derived from code and locked tests
- **Deep Dives** — architecture, CFG semantics, integrations, and operational rationale

!!! note "Licensing"
    CodeClone source code is licensed under MPL-2.0.

    Documentation content under `docs/` and the published docs site are
    licensed under MIT.

---

## Start Here

### New to CodeClone?

Understand the deterministic review model and governance philosophy.

- [Contracts and guarantees](book/00-intro.md)
- [Architecture map (components + ownership)](book/01-architecture-map.md)
- [Terminology](book/02-terminology.md)

### Integrating into CI?

Set up baseline-aware gating and deterministic review flows.

- [Exit codes and failure policy](book/03-contracts-exit-codes.md)
- [Metrics mode and quality gates](book/15-metrics-and-quality-gates.md)
- [Baseline contract](book/06-baseline.md)

### Using IDEs or AI agents?

Understand the canonical review surfaces and MCP contract.

- [MCP interface contract](book/20-mcp-interface.md)
- [VS Code extension](book/21-vscode-extension.md)
- [Codex plugin](book/23-codex-plugin.md)

### Reviewing reports?

Explore the canonical report model and rendered review surfaces.

- [Report contract](book/08-report.md)
- [HTML report rendering](book/10-html-render.md)
- [Live sample report](examples/report.md)

---

## Contracts Book

Contract-first documentation derived from code and locked tests.

The Contracts Book defines:

- schemas and typed contracts
- baseline and cache semantics
- exit codes and CI behavior
- determinism guarantees
- trust and compatibility rules
- review surface contracts

### Core Contracts

- [Exit codes and failure policy](book/03-contracts-exit-codes.md)
- [Config and defaults](book/04-config-and-defaults.md)
- [Core pipeline and invariants](book/05-core-pipeline.md)
- [Baseline contract (schema v2.1)](book/06-baseline.md)
- [Cache contract (schema v2.7)](book/07-cache.md)
- [Report contract (schema v2.11)](book/08-report.md)

### Interfaces

- [CLI behavior, modes, and UX](book/09-cli.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [VS Code extension contract](book/21-vscode-extension.md)
- [Claude Desktop bundle contract](book/22-claude-desktop-bundle.md)
- [Codex plugin contract](book/23-codex-plugin.md)
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

Narrative documentation covering architecture, integrations, and operational usage.

- [Architecture narrative](architecture.md)
- [CFG design and semantics](cfg.md)
- [MCP integration for AI agents and clients](mcp.md)
- [VS Code extension usage guide](vscode-extension.md)
- [Claude Desktop bundle usage guide](claude-desktop-bundle.md)
- [Codex plugin usage guide](codex-plugin.md)
- [SARIF integration for IDE/code-scanning use](sarif.md)

### Operational and legal

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

=== "Build the site"

    ```bash title="Validate the docs site"
    uv run --with mkdocs --with mkdocs-material mkdocs build --strict
    ```

=== "Build the site and sample report"

    ```bash title="Generate the live sample report into the built site"
    uv run --with mkdocs --with mkdocs-material mkdocs build --strict
    uv run python scripts/build_docs_example_report.py --output-dir site/examples/report/live
    ```

!!! note "Generated output"
    `site/` is generated output used for local preview and GitHub Pages
    publishing. It is not committed to git.

GitHub Pages publishing is handled by
[`docs.yml`](https://github.com/orenlab/codeclone/blob/main/.github/workflows/docs.yml)
via a custom Actions workflow.
