# CodeClone for Codex

Native Codex plugin for structural code quality analysis over `codeclone-mcp`.

Same canonical MCP surface used by CLI, VS Code, Claude Desktop, and Claude Code.
Read-only, baseline-aware, local stdio only.

## What ships here

| File                         | Purpose                                            |
|------------------------------|----------------------------------------------------|
| `.codex-plugin/plugin.json`  | Plugin metadata and prompts                        |
| `.mcp.json`                  | Local `codeclone-mcp --transport stdio` definition |
| `skills/codeclone-review/`   | Conservative-first full review skill               |
| `skills/codeclone-hotspots/` | Quick hotspot discovery skill                      |
| `assets/`                    | Plugin branding                                    |

## Install

`codeclone-mcp` must be on `PATH`:

```bash
uv tool install --pre "codeclone[mcp]"
codeclone-mcp --help                       # verify
```

If you want to keep the launcher inside an existing environment instead, use
`uv pip install --pre "codeclone[mcp]"`.

Codex discovers the plugin from `.agents/plugins/marketplace.json`.
It does not rewrite `~/.codex/config.toml`.

If you prefer manual MCP registration instead:

```bash
codex mcp add codeclone -- codeclone-mcp --transport stdio
```

## Skills

**codeclone-review** — full structural review: conservative first pass,
baseline-aware triage, changed-files review, deeper exploratory follow-up.

**codeclone-hotspots** — quick quality snapshot: health check, top risks,
single-metric queries, pre-merge sanity checks.

## Links

- [Codex plugin guide](https://orenlab.github.io/codeclone/codex-plugin/)
- [MCP usage guide](https://orenlab.github.io/codeclone/mcp/)
- [Privacy Policy](https://orenlab.github.io/codeclone/privacy-policy/)
