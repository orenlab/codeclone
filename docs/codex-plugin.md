# Codex Plugin

**Structural Change Controller for AI-assisted Python development** — native
Codex plugin. Source lives in `plugins/codeclone/`; public installs use the
distribution repo `orenlab/codeclone-codex`.

## What ships in the plugin

| File                                   | Purpose                                 |
|----------------------------------------|-----------------------------------------|
| `.codex-plugin/plugin.json`            | Plugin metadata, prompts, instructions  |
| `.mcp.json`                            | Workspace-first MCP launcher definition |
| `scripts/launch_mcp`                   | Shell-free launcher wrapper for Codex   |
| `skills/codeclone-review/`             | Conservative-first full review skill    |
| `skills/codeclone-hotspots/`           | Quick hotspot discovery skill           |
| `skills/codeclone-change-control/`     | Intent-first change workflow skill      |
| `skills/codeclone-engineering-memory/` | Engineering memory read/write skill     |
| `assets/`                              | Plugin branding                         |

## Install

Install the plugin from the Codex marketplace:

```bash
marketplace add orenlab/codeclone-codex
```

The plugin manifest version tracks the CodeClone package release line (currently
`2.1.0a1` in this monorepo). It describes the bundled guidance surface, not the
live MCP tool count — tools come from the resolved `codeclone-mcp` server.

The plugin expects a local `codeclone-mcp` command. Install CodeClone with the
MCP extra in the workspace or globally:

```bash
uv venv
uv pip install --python .venv/bin/python "codeclone[mcp]"
.venv/bin/codeclone-mcp --help
```

Global fallback:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --help
```

Manual MCP registration without the plugin:

```bash
codex mcp add codeclone -- codeclone-mcp --transport stdio
```

## Skills

### codeclone-review

Full structural review: clone triage, changed-scope review, health-oriented
refactor planning. Starts conservative with default thresholds, supports
deeper follow-up with lowered thresholds and run comparison.

### codeclone-hotspots

Quick quality snapshot: health check, top risks, single-metric queries.
The cheapest useful path — `analyze_repository` then `get_production_triage`.

### codeclone-change-control

Intent-first change workflow for repository edits. Declares scope before
editing, maps blast radius, verifies the patch against the contract, generates
a review receipt, and validates cited review claims. This is the governance
skill — use it whenever the task requires changing files.

### codeclone-engineering-memory

Scope-aware Engineering Memory over MCP: `get_relevant_memory` (absolute
`root` required), `query_engineering_memory`, draft `record_candidate`, and
`finish(..., propose_memory=true)`. Complements change control — does not replace
intent declaration or patch verify. Human approve stays in the CodeClone VS Code
**Memory** view (not MCP).

Optional **semantic search** (Phase 20): off by default in
`[tool.codeclone.memory.semantic]`; when enabled, install
`codeclone[semantic-lancedb]`, rebuild the index, then
`query_engineering_memory(mode=search, semantic=true)`. Default provider
`diagnostic` is deterministic, not semantic-quality embeddings. See
[Engineering Memory](book/26-engineering-memory.md).

## Runtime model

Additive — the marketplace install provides a local MCP definition and **four**
skills. New canonical MCP surfaces from the local `codeclone-mcp` version flow
through directly, including Coverage Join facts and the optional `coverage`
help topic when supported. The plugin does not mutate `~/.codex/config.toml` or
install a second server binary. The bundled launcher does not filter MCP tools;
agents receive the **31-tool** agent surface from the resolved `codeclone-mcp`
server (no `--ide-governance-channel` — IDE-only session/audit tools are VS Code
only).

`.agents/plugins/marketplace.json` is the monorepo-local source entry used for
development and packaging into `orenlab/codeclone-codex`; it is not the public
install path.

## Read-only contract

Repository truth stays read-only: MCP must not mutate source files, baselines,
analysis cache, or canonical report artifacts. Change-control and session tools
may write ephemeral coordination state through the configured workspace intent
registry (file or SQLite backend) and optional audit records when enabled.

## Current limits

- If you already registered `codeclone-mcp` manually, keep only one setup path
  to avoid duplicate MCP surfaces.
- The bundled `.mcp.json` prefers `.venv`, then a Poetry env, then `PATH`.
- The bundled launcher stays shell-free and local-stdio-only.

## Further reading

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [Engineering Memory](book/26-engineering-memory.md)
- [Structural Change Controller](book/24-structural-change-controller.md)
