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
| `scripts/launch_mcp`         | Shell-free workspace-first launcher bootstrap      |
| `skills/codeclone-review/`   | Conservative-first full review skill               |
| `skills/codeclone-hotspots/` | Quick hotspot discovery skill                      |
| `assets/`                    | Plugin branding                                    |

`plugin.json` keeps the machine identifier as lowercase `codeclone`; the
user-facing label stays in `interface.displayName` as `CodeClone`.

## Install

The plugin prefers a workspace launcher first:

1. `./.venv/bin/codeclone-mcp`
2. the current Poetry environment launcher
3. `codeclone-mcp` from `PATH`

The bundled Codex launcher is a small repo-local Python wrapper, not a shell
snippet. It keeps the same workspace-first order without relying on `sh -lc`.

Recommended workspace-local setup:

```bash
uv venv
uv pip install --python .venv/bin/python "codeclone[mcp]"
.venv/bin/codeclone-mcp --help
```

If your workspace uses Poetry, install CodeClone into that Poetry environment.

Global fallback:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --help
```

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
