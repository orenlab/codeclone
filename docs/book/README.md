<!-- doc-scope: SINGLE CANONICAL TOC for the Contracts Book.
     owns: chapter listing with group headings, reading-order guidance.
     does-not-own: chapter content.
     rule: other files (index.md, nav) link here — they do NOT duplicate this TOC.
       Do not add chapter summaries — keep it a pure link list. -->

# CodeClone Contracts Book

This book is the contract-level documentation for CodeClone v2.x.

All guarantees here are derived from code and locked tests.
If a statement is not enforced by code/tests, it is explicitly marked as non-contractual.

!!! note "Contract rule"
    If this book and the current repository code diverge, code and locked tests
    win. Update the book after correcting the implementation or contract test.

## How to read

- Start with **Terminology → Architecture map → Intro**.
- Then read the **pipeline spine**: Core pipeline → CFG → Report → HTML render → Baseline → Cache.
- **Change control** (Structural Change Controller, Engineering Memory, Claim Guard) is the governance layer.
- Everything else is supporting detail, invariants, and reference.

## Table of Contents

### Foundations

- [00-intro.md](00-intro.md) — book charter and goals
- [01-terminology.md](01-terminology.md) — glossary
- [02-architecture-map.md](02-architecture-map.md) — authoritative module table

### Pipeline and data

- [03-core-pipeline.md](03-core-pipeline.md) — canonical pipeline contract
- [04-cfg-semantics.md](04-cfg-semantics.md) — CFG design and semantics
- [05-report.md](05-report.md) — report contract (schema v2.11)
- [06-html-render.md](06-html-render.md) — HTML rendering contract
- [07-baseline.md](07-baseline.md) — baseline contract (schema v2.1)
- [08-cache.md](08-cache.md) — cache contract (schema v2.8)

### Contracts and config

- [09-exit-codes.md](09-exit-codes.md) — exit codes and failure policy
- [10-config-and-defaults.md](10-config-and-defaults.md) — config reference
- [11-cli.md](11-cli.md) — CLI behavior and modes

### Change control

- [12-structural-change-controller/index.md](12-structural-change-controller/index.md) — overview
- [12-structural-change-controller/finish-controlled-change.md](12-structural-change-controller/finish-controlled-change.md) —
  finish pipeline
- [12-structural-change-controller/finish-hygiene.md](12-structural-change-controller/finish-hygiene.md) — hygiene
  blocking vs advisory
- [12-structural-change-controller/patch-trail.md](12-structural-change-controller/patch-trail.md) — Patch Trail
- [13-engineering-memory/index.md](13-engineering-memory/index.md) — evidence-linked repository memory
- [14-claim-guard.md](14-claim-guard.md) — review claim validation

### Quality signals

- [15-health-score.md](15-health-score.md) — health score model
- [16-metrics-and-quality-gates.md](16-metrics-and-quality-gates.md) — metrics mode and gate flags
- [17-dead-code-contract.md](17-dead-code-contract.md) — dead-code detection and test-boundary policy
- [18-suggestions-and-clone-typing.md](18-suggestions-and-clone-typing.md) — suggestions and clone typing
- [19-inline-suppressions.md](19-inline-suppressions.md) — `# codeclone: ignore[...]`
- [20-benchmarking.md](20-benchmarking.md) — reproducible Docker benchmarking

### System properties

- [21-security-model.md](21-security-model.md) — security model and threat boundaries
- [22-determinism.md](22-determinism.md) — determinism policy
- [23-testing-as-spec.md](23-testing-as-spec.md) — tests as specification
- [24-compatibility-and-versioning.md](24-compatibility-and-versioning.md) — compatibility and versioning rules
- [26-platform-observability.md](26-platform-observability.md) — local diagnostics for CodeClone's own runtime
- [27-corpus-analytics.md](27-corpus-analytics.md) — offline intent corpus clustering (optional `[analytics]`)

### MCP interface

- [25-mcp-interface/index.md](25-mcp-interface/index.md) — MCP interface contract
- [25-mcp-interface/tools/workflow.md](25-mcp-interface/tools/workflow.md) — workflow tools
- [25-mcp-interface/resources.md](25-mcp-interface/resources.md) — resource URIs
- [25-mcp-interface/tools/platform-observability.md](25-mcp-interface/tools/platform-observability.md) — bounded
  diagnostics tool

### Integrations

- [integrations/vs-code-extension.md](integrations/vs-code-extension.md) — VS Code extension contract
- [integrations/cursor-plugin.md](integrations/cursor-plugin.md) — Cursor plugin contract
- [integrations/claude-code-plugin.md](integrations/claude-code-plugin.md) — Claude Code plugin contract
- [integrations/codex-plugin.md](integrations/codex-plugin.md) — Codex plugin contract
- [integrations/claude-desktop-bundle.md](integrations/claude-desktop-bundle.md) — Claude Desktop bundle contract
- [integrations/sarif.md](integrations/sarif.md) — SARIF projection contract

### Appendix

- [appendix/a-status-enums.md](appendix/a-status-enums.md) — status enums and typed contracts
- [appendix/b-schema-layouts.md](appendix/b-schema-layouts.md) — schema layouts (baseline/cache/report)
- [appendix/c-error-catalog.md](appendix/c-error-catalog.md) — error catalog (contract vs internal)
