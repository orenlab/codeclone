<!-- doc-scope: MCP GUIDE HUB. class: guide max-lines: 90 -->
# MCP for AI Agents

Use CodeClone through `codeclone-mcp` — same pipeline and report as the CLI.

**Analysis truth is read-only:** MCP never mutates source, baselines, analysis
cache, or canonical reports. It **may** write session-local coordination
(workspace intents), Engineering Memory **drafts**, and optional audit rows when
enabled. Opt-in Platform Observability writes separate local development
telemetry and never becomes repository truth.

Install: [Getting started — MCP extra](../../getting-started.md#install).

!!! tip "Guide vs contract"
    This section is **how to work** with MCP. Tool names, parameters, and response
    shapes are normative in the [MCP interface contract](../../book/25-mcp-interface/index.md).

## Setup

| Step | Page |
|------|------|
| Register a client | [Client setup](client-setup.md) |
| Launcher & transport | [Server & transport](server-and-transport.md) |
| Layer diagram | [Architecture](architecture.md) |
| Common failures | [Troubleshooting](troubleshooting.md) |

## Workflows (recommended order)

| Phase | Recipe |
|-------|--------|
| 1. Baseline-aware triage | [Analyze & triage](workflows/analyze-and-triage.md) |
| 2. Focused inspection | [Drill down & checks](workflows/drill-down-and-checks.md) |
| 3. Governed edits | [Change control](workflows/change-control.md) |
| 4. Durable scope context | [Memory recipes](workflows/memory-recipes.md) |
| 5. Coverage & session | [Session & coverage](workflows/session-and-coverage.md) |

## Reference shortcuts

| Need | Page |
|------|------|
| Prompt patterns | [Prompt patterns](prompts.md) |
| Payload field cheat sheet | [Payload cheatsheet](payload-cheatsheet.md) |
| Change control contract | [Structural Change Controller](../../book/12-structural-change-controller/index.md) |
| Engineering Memory contract | [Engineering Memory](../../book/13-engineering-memory/index.md) |
| Runtime diagnostics | [Platform Observability](../observability/diagnostics.md) |
