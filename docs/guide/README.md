<!-- doc-scope: GUIDE HUB. class: guide max-lines: 90 -->

# Guide

Recipes and workflows for humans and AI agents. For normative guarantees (schemas,
enums, payload semantics), use the [Contracts book](../book/README.md).

!!! abstract "Who is this for?"
    - **Developers** — install, CI, first analysis run
    - **Agent authors** — MCP workflows, change control, memory recipes
    - **IDE and agent users** — VS Code, Cursor, Claude Code, Codex, Claude Desktop setup

## Start here

| I want to…                                      | Page                                                                   |
|-------------------------------------------------|------------------------------------------------------------------------|
| Install and run locally                         | [Getting started](../getting-started.md)                               |
| Understand the pipeline                         | [How CodeClone works](explanation/how-it-works.md)                     |
| Connect an AI agent via MCP                     | [MCP overview](mcp/README.md)                                          |
| Govern agent edits                              | [Change control overview](change-control/overview.md)                  |
| Scope context before edits                      | [Engineering Memory overview](memory/overview.md)                      |
| Inspect trajectory history and patterns         | [Trajectories and Experiences](memory/trajectories-and-experiences.md) |
| Diagnose CodeClone's own runtime *(maintainer)* | [Platform Observability](observability/diagnostics.md)                 |
| Cluster historical agent intents *(maintainer)* | [Corpus Analytics](analytics/overview.md)                              |

## MCP workflows

| Task                             | Recipe                                                                   |
|----------------------------------|--------------------------------------------------------------------------|
| First analysis pass              | [Analyze & triage](mcp/workflows/analyze-and-triage.md)                  |
| Hotspots and checks              | [Drill down & checks](mcp/workflows/drill-down-and-checks.md)            |
| Declare → edit → finish          | [Change control](mcp/workflows/change-control.md)                        |
| Memory before/after edits        | [Memory recipes](mcp/workflows/memory-recipes.md)                        |
| Cobertura join & session markers | [Coverage join & session markers](mcp/workflows/session-and-coverage.md) |

## Integrations

| Client         | Setup guide                                                   | Contract                                                  |
|----------------|---------------------------------------------------------------|-----------------------------------------------------------|
| VS Code        | [Setup](integrations/vscode/setup.md)                         | [Contract](../book/integrations/vs-code-extension.md)     |
| Cursor         | [Install & skills](integrations/cursor/install-and-skills.md) | [Contract](../book/integrations/cursor-plugin.md)         |
| Claude Code    | [Install](integrations/claude-code/setup.md)                  | [Contract](../book/integrations/claude-code-plugin.md)    |
| Codex          | [Install](integrations/codex/setup.md)                        | [Contract](../book/integrations/codex-plugin.md)          |
| Claude Desktop | [Setup](integrations/claude-desktop/setup.md)                 | [Contract](../book/integrations/claude-desktop-bundle.md) |
| GitHub Action  | [CI setup](../getting-started.md#ci-setup)                    | [Contract](../book/integrations/github-action.md)         |
| SARIF export   | [Export](integrations/sarif/export.md)                        | [Contract](../book/integrations/sarif.md)                 |
