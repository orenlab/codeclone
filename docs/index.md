<!-- doc-scope: GOAL-ROUTER LANDING PAGE.
     owns: intro paragraph, goal→link routing tables.
     does-not-own: full book TOC (book/README.md), install instructions
       (getting-started.md), local preview commands (publishing.md).
     rule: keep under 95 lines. Add links, not content. -->

# CodeClone Docs

> Structural Change Controller for AI-assisted Python development —
> deterministic, baseline-aware, built for CI and AI agents.

CodeClone runs one deterministic analysis pipeline and emits a canonical JSON
report. Every surface — CLI, HTML, MCP, IDE — is a projection of that report.
Humans and AI agents operate on the same structural facts.

The v2.1 change controller starts before the first edit: an agent declares what
it intends to change, CodeClone maps the structural blast radius, verifies the
patch against the declared boundary, and generates an auditable review receipt.

!!! note "Documentation for the in-development v2.1 line"
    This site tracks the unreleased **v2.1** line; for the current stable release
    see [CodeClone v2.0.2](https://github.com/orenlab/codeclone/tree/v2.0.2).

## New here? Follow the path

1. [**Install & first run**](getting-started.md) — install, analyze a repo, read the report.
2. [**Connect your agent**](getting-started.md#mcp-setup) — wire CodeClone into your IDE or agent.
3. [**Your first governed edit**](start/first-governed-edit.md) — declare → edit → verify, end to end.

!!! tip "Two tabs — pick one mental model"
    **Guide** — install, run, MCP workflows, IDE setup, recipes.
    Start at the [Guide hub](guide/README.md).

    **Contracts** — normative guarantees, schemas, enums, payload semantics.
    Start at the [Contracts book](book/README.md).

!!! note "Licensing"
    Source code: MPL-2.0. Documentation and docs-site content: MIT.

---

## Getting Started

| Goal                  | Start here                                        |
|-----------------------|---------------------------------------------------|
| First install and run | [Getting started](getting-started.md)             |
| Understand the model  | [How it works](guide/explanation/how-it-works.md) |
| Terminology lookup    | [Terminology](book/01-terminology.md)             |

## CI and Gating

| Goal                          | Start here                                                |
|-------------------------------|-----------------------------------------------------------|
| Baseline-aware CI             | [Getting started: CI setup](getting-started.md#ci-setup)  |
| Exit codes and failure policy | [Exit codes](book/09-exit-codes.md)                       |
| Quality gates and metrics     | [Metrics and gates](book/16-metrics-and-quality-gates.md) |
| Baseline contract             | [Baseline](book/07-baseline.md)                           |

## AI Agent Governance

| Goal                                | Start here                                                                    |
|-------------------------------------|-------------------------------------------------------------------------------|
| MCP usage (workflows, setup)        | [MCP guide](guide/mcp/README.md)                                              |
| First governed edit (tutorial)      | [Your first governed edit](start/first-governed-edit.md)                      |
| Change controller workflow          | [Structural Change Controller](book/12-structural-change-controller/index.md) |
| Engineering Memory (scope context)  | [Engineering Memory](book/13-engineering-memory/index.md)                     |
| Trajectories and recurring patterns | [Trajectories and Experiences](guide/memory/trajectories-and-experiences.md)  |
| MCP interface contract              | [MCP interface](book/25-mcp-interface/index.md)                               |

## IDE and Agent Clients

| Surface               | Guide (how to)                                                      | Contract (guarantees)                                                 |
|-----------------------|---------------------------------------------------------------------|-----------------------------------------------------------------------|
| VS Code extension     | [Setup](guide/integrations/vscode/setup.md)                         | [VS Code contract](book/integrations/vs-code-extension.md)            |
| Cursor plugin         | [Install & skills](guide/integrations/cursor/install-and-skills.md) | [Cursor contract](book/integrations/cursor-plugin.md)                 |
| Claude Code plugin    | [Install](guide/integrations/claude-code/setup.md)                  | [Claude Code contract](book/integrations/claude-code-plugin.md)       |
| Codex plugin          | [Install](guide/integrations/codex/setup.md)                        | [Codex contract](book/integrations/codex-plugin.md)                   |
| Claude Desktop bundle | [Setup](guide/integrations/claude-desktop/setup.md)                 | [Claude Desktop contract](book/integrations/claude-desktop-bundle.md) |
| GitHub Action         | [CI setup](getting-started.md#ci-setup)                             | [GitHub Action contract](book/integrations/github-action.md)          |
| SARIF & code scanning | [Export](guide/integrations/sarif/export.md)                        | [SARIF contract](book/integrations/sarif.md)                          |

## Reports

| Goal                    | Start here                            |
|-------------------------|---------------------------------------|
| Report model and schema | [Report contract](book/05-report.md)  |
| HTML rendering          | [HTML render](book/06-html-render.md) |
| Live sample             | [Sample report](examples/report.md)   |

## Maintainers & internals

Operating or building CodeClone itself? See [Platform Observability](guide/observability/diagnostics.md)
and [Corpus Analytics](guide/analytics/overview.md) under the **Maintainers** tab.

**Editions & plans** — CodeClone is open source and runs locally; Team and Enterprise add scaled retention, managed
options, and support. Pick the level that fits your needs: [Plans and retention](plans-and-retention.md).
