# Codex Plugin

CodeClone ships a native Codex plugin. Source lives in `plugins/codeclone/`;
public installs use the distribution repo `orenlab/codeclone-codex`.

## What ships in the plugin

| File | Purpose |
|------|---------|
| `.codex-plugin/plugin.json` | Plugin metadata, prompts, instructions |
| `.mcp.json` | Workspace-first MCP launcher definition |
| `scripts/launch_mcp` | Shell-free launcher wrapper for Codex |
| `skills/codeclone-review/` | Conservative-first full review skill |
| `skills/codeclone-hotspots/` | Quick hotspot discovery skill |
| `skills/codeclone-change-control/` | Intent-first change workflow skill |
| `assets/` | Plugin branding |

## Install

Install the plugin from the Codex marketplace:

```bash
marketplace add orenlab/codeclone-codex
```

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

## Runtime model

Additive — the marketplace install provides a local MCP definition and three
skills. New canonical MCP surfaces from the local `codeclone-mcp` version flow
through directly, including Coverage Join facts and the optional `coverage`
help topic when supported. The plugin does not mutate `~/.codex/config.toml` or
install a second server binary.

`.agents/plugins/marketplace.json` is the monorepo-local source entry used for
development and packaging into `orenlab/codeclone-codex`; it is not the public
install path.

## Current limits

- If you already registered `codeclone-mcp` manually, keep only one setup path
  to avoid duplicate MCP surfaces.
- The bundled `.mcp.json` prefers `.venv`, then a Poetry env, then `PATH`.
- The bundled launcher stays shell-free and local-stdio-only.

## Further reading

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [Structural Change Controller](book/24-structural-change-controller.md)
