<!-- doc-scope: GOAL-ROUTER LANDING PAGE.
     owns: intro paragraph, goal→link routing tables.
     does-not-own: full book TOC (book/README.md), install instructions
       (getting-started.md), local preview commands (publishing.md).
     rule: keep under 80 lines. Add links, not content. -->
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
| Terminology lookup    | [Terminology](book/01-terminology.md)        |

## CI and Gating

| Goal                          | Start here                                                |
|-------------------------------|-----------------------------------------------------------|
| Baseline-aware CI             | [Getting started: CI setup](getting-started.md#ci-setup)  |
| Exit codes and failure policy | [Exit codes](book/09-exit-codes.md)                       |
| Quality gates and metrics     | [Metrics and gates](book/16-metrics-and-quality-gates.md) |
| Baseline contract             | [Baseline](book/07-baseline.md)                           |

## AI Agent Governance

| Goal                               | Start here                                                              |
|------------------------------------|-------------------------------------------------------------------------|
| Change controller workflow         | [Structural Change Controller](book/12-structural-change-controller.md) |
| Engineering Memory (scope context) | [Engineering Memory](book/13-engineering-memory.md)                     |
| MCP interface contract             | [MCP interface](book/25-mcp-interface.md)                               |
| MCP usage guide                    | [MCP guide](mcp.md)                                                     |

## IDE and Agent Clients

| Surface               | Page                                       |
|-----------------------|--------------------------------------------|
| VS Code extension     | [VS Code](vscode-extension.md)             |
| Claude Desktop bundle | [Claude Desktop](claude-desktop-bundle.md) |
| Codex plugin          | [Codex](codex-plugin.md)                   |
| Cursor plugin         | [Cursor](cursor-plugin.md)                 |
| SARIF & code scanning | [SARIF](sarif.md)                          |

## Reports

| Goal                    | Start here                            |
|-------------------------|---------------------------------------|
| Report model and schema | [Report contract](book/05-report.md)  |
| HTML rendering          | [HTML render](book/06-html-render.md) |
| Live sample             | [Sample report](examples/report.md)   |
