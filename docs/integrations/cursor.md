---
title: "Cursor integration"
audience: public
doc_type: guide
status: published
source_commit: "60eac9c367d74deeba1478521461addfedd8e681"
---

## What it is

The CodeClone MCP integration for Cursor enables AI-powered code analysis and change control directly in the editor. Through Cursor's MCP (Model Context Protocol) server support, you can run CodeClone analysis, review patch contracts, and track engineering memory without leaving your IDE.

## When to use it

Use the Cursor integration when you:

- Need live structural feedback on Python code before committing
- Want change control gates on risky patches (high complexity, coupling, or clones)
- Track and recover from previous analysis decisions via engineering memory
- Review PR quality across your team using standardized baselines
- Debug reproducible findings (clones, dead code, structural issues)

## Basic workflow

```mermaid
graph LR
    A["Open Python file<br/>in Cursor"] --> B["Trigger analyze<br/>via MCP"]
    B --> C["View findings<br/>in sidebar"]
    C --> D["Select finding<br/>for detail"]
    D --> E["Review remediation<br/>hints & memory"]
    E --> F{Ready to<br/>commit?}
    F -->|No| G["Edit & re-analyze"]
    G --> B
    F -->|Yes| H["Run change control"]
    H --> I["Accept patch<br/>or revise"]
```

## Key commands

The integration exposes these MCP tools through Cursor's interface:

| Command | Purpose | When to use |
|---------|---------|-------------|
| `analyze_repository` | Full structural analysis from repo root | First pass, before major refactoring |
| `analyze_changed_paths` | Focused review of changed files only | During PR review, local branches |
| `start_controlled_change` | Declare intent, compute blast radius | Before editing large chunks |
| `finish_controlled_change` | Verify patch, record trail, accept/reject | After editing, before commit |
| `get_implementation_context` | Bounded structural & call-graph facts | Planning edits, understanding scope |
| `get_production_triage` | Health snapshot with hotspots | Quick health check |

## Install

First install the CodeClone MCP runtime:

```bash
uv tool install --prerelease allow "codeclone[mcp]"
```

The Cursor plugin bundles the launcher and configures MCP for you. To configure it manually instead, add a `.cursor/mcp.json` in your project that runs the installed `codeclone-mcp` entry point over stdio:

```json
{
  "mcpServers": {
    "codeclone": {
      "command": "codeclone-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

The plugin's own launcher invokes `python3 ./scripts/launch_mcp.py`; the manual config above is the equivalent when you have `codeclone[mcp]` installed on your PATH.

## Bundled skills, rules, and hooks

The Cursor plugin ships:

- **10 skills** — the same set as the [Claude integration](claude.md#bundled-skills) (change control, review, triage, blast radius, implementation context, hotspots, engineering memory, setup, architecture triage, platform observability).
- **3 rules** (`.mdc`) — `change-control-gate`, `codeclone-python`, `codeclone-workflow`.
- **Change-control hooks** — a pre-tool-use gate and a post-edit hook that enforce the intent-first workflow around Python edits.

## Common mistakes

**Mistake 1: Absolute paths in MCP calls**
MCP tools require absolute repository roots. Relative paths like `.` are rejected. Always pass the full workspace path.

**Mistake 2: Forgetting `start_controlled_change` before editing**
Declaring intent first ensures the change control workflow captures blast radius and budget. Skipping it makes `finish_controlled_change` unable to verify scope.

**Mistake 3: Mixing before and after analysis runs**
For Python structural changes, you must run `analyze_repository` before editing and again after. A single run cannot verify both states.

**Mistake 4: Ignoring stale memory warnings**
Engineering memory may reference outdated decisions or contradictions. Always review memory alerts before relying on recorded facts.

## Next steps

- Read [Engineering Memory](../concepts/engineering-memory.md) to understand how CodeClone tracks decisions across sessions
- Explore MCP tool details with the in-tool `help(topic="overview")` call, or the [MCP tools reference](../reference/mcp-tools.md)
- Set up baseline thresholds in `pyproject.toml` to match your team's standards
- Use `generate_pr_summary(format="markdown")` to produce a compact PR summary — see the [MCP tools reference](../reference/mcp-tools.md)
