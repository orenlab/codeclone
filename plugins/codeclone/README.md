# CodeClone for Codex

Native Codex plugin for structural code quality analysis over `codeclone-mcp`.

Same canonical MCP surface used by CLI, VS Code, Claude Desktop, and Claude Code.
Read-only, baseline-aware, local stdio only.
Current-run metric surfaces from the local `codeclone-mcp` version flow through
directly, including `Coverage Join` facts and the optional `coverage` help topic.

## What ships here

| File                         | Purpose                                            |
|------------------------------|----------------------------------------------------|
| `.codex-plugin/plugin.json`  | Plugin metadata and prompts                        |
| `.mcp.json`                  | Local stdio MCP definition                         |
| `scripts/launch_mcp`         | Shell-free trusted-launcher bootstrap              |
| `skills/codeclone-review/`   | Conservative-first full review skill               |
| `skills/codeclone-hotspots/` | Quick hotspot discovery skill                      |
| `assets/`                    | Plugin branding                                    |

`plugin.json` keeps the machine identifier as lowercase `codeclone`; the
user-facing label stays in `interface.displayName` as `CodeClone`.

## Install

The plugin starts only a trusted launcher, in this order:

1. the absolute path in `CODECLONE_MCP_COMMAND`, when you set it
2. `codeclone-mcp` from an absolute `PATH` directory

Opening a repository is not consent to run programs from it: the launcher never starts a `codeclone-mcp` from the opened workspace (`.venv`, `venv`, a Poetry environment, or a relative `PATH` entry). If none is found, the launcher exits
with a setup message instead of guessing.

The bundled Codex launcher is a small repo-local Python wrapper, not a shell
snippet, so it does this without relying on `sh -lc`.

Recommended setup:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --help
```

To use CodeClone from a specific virtual environment instead, set
`CODECLONE_MCP_COMMAND` to the absolute path of its `codeclone-mcp`.

Codex discovers the plugin from `.agents/plugins/marketplace.json`.
It does not rewrite `~/.codex/config.toml`.

If you prefer manual MCP registration instead:

```bash
codex mcp add codeclone -- codeclone-mcp --transport stdio
```

## Skills

**codeclone-review** — full structural review: conservative first pass,
baseline-aware triage, changed-files review, deeper exploratory follow-up,
current-run metrics surfaces.

**codeclone-hotspots** — quick quality snapshot: health check, top risks,
single-metric queries, pre-merge sanity checks, coverage/adoption/API snapshots.

## Links

- [Codex plugin guide](https://orenlab.github.io/codeclone/codex-plugin/)
- [MCP usage guide](https://orenlab.github.io/codeclone/mcp/)
- [Privacy Policy](https://orenlab.github.io/codeclone/privacy-policy/)
