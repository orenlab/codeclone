# Codex Plugin

CodeClone ships a native Codex plugin in `plugins/codeclone/`.
Repo-local discovery via `.agents/plugins/marketplace.json`.

## What ships in the plugin

| File                         | Purpose                                            |
|------------------------------|----------------------------------------------------|
| `.codex-plugin/plugin.json`  | Plugin metadata, prompts, instructions             |
| `.mcp.json`                  | Local `codeclone-mcp --transport stdio` definition |
| `skills/codeclone-review/`   | Conservative-first full review skill               |
| `skills/codeclone-hotspots/` | Quick hotspot discovery skill                      |
| `assets/`                    | Plugin branding                                    |

## Install

```bash
uv tool install --pre "codeclone[mcp]"    # or: uv pip install --pre "codeclone[mcp]"
codeclone-mcp --help                # verify
```

Manual MCP registration without the plugin:

```bash
codex mcp add codeclone -- codeclone-mcp --transport stdio
```

## Runtime model

Additive — Codex discovers the plugin from `.agents/plugins/marketplace.json`,
gets a local MCP definition and two skills. Does not mutate
`~/.codex/config.toml` or install a second server binary.

## Current limits

- if you already registered `codeclone-mcp` manually, keep only one setup path
  to avoid duplicate MCP surfaces
- the bundled `.mcp.json` assumes `codeclone-mcp` resolves on `PATH`

For the underlying interface contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
