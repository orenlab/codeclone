# Codex Plugin

CodeClone ships a native Codex plugin in `plugins/codeclone/`.
Repo-local discovery via `.agents/plugins/marketplace.json`.

## What ships in the plugin

| File                         | Purpose                                            |
|------------------------------|----------------------------------------------------|
| `.codex-plugin/plugin.json`  | Plugin metadata, prompts, instructions             |
| `.mcp.json`                  | Workspace-first MCP launcher definition            |
| `skills/codeclone-review/`   | Conservative-first full review skill               |
| `skills/codeclone-hotspots/` | Quick hotspot discovery skill                      |
| `assets/`                    | Plugin branding                                    |

## Install

```bash
uv venv
uv pip install --python .venv/bin/python "codeclone[mcp]>=2.0.0b5"
.venv/bin/codeclone-mcp --help
```

Global fallback:

```bash
uv tool install "codeclone[mcp]>=2.0.0b5"
codeclone-mcp --help
```

Manual MCP registration without the plugin:

```bash
codex mcp add codeclone -- codeclone-mcp --transport stdio
```

## Runtime model

Additive — Codex discovers the plugin from `.agents/plugins/marketplace.json`,
gets a local MCP definition and two skills. New canonical MCP surfaces from the
local `codeclone-mcp` version flow through directly, including `Coverage Join`
facts and the optional `coverage` help topic when supported. The plugin does
not mutate `~/.codex/config.toml` or install a second server binary.

## Current limits

- if you already registered `codeclone-mcp` manually, keep only one setup path
  to avoid duplicate MCP surfaces
- the bundled `.mcp.json` prefers `.venv`, then a Poetry env, then `PATH`

For the underlying interface contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
