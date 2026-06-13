<!-- doc-scope: Codex Plugin contract. class: contract max-lines: 150 -->

# Codex Plugin

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

## Runtime model

Additive — the marketplace install provides a local MCP definition and **four**
skills. New canonical MCP surfaces from the local `codeclone-mcp` version flow
through directly, including Coverage Join facts and the optional `coverage`
help topic when supported. The plugin does not mutate `~/.codex/config.toml` or
install a second server binary. The bundled launcher does not filter MCP tools;
agents receive the full default agent surface from the resolved
`codeclone-mcp` server (no `--ide-governance-channel` — IDE-only session/audit
tools are VS Code only).

`.agents/plugins/marketplace.json` is the monorepo-local source entry used for
development and packaging into `orenlab/codeclone-codex`; it is not the public
install path.

Public installation is:

```bash
codex plugin marketplace add orenlab/codeclone-codex
codex plugin add codeclone@orenlab-codeclone
```

## Read-only contract

Repository truth stays read-only: MCP must not mutate source files, baselines,
analysis cache, or canonical report artifacts. Change-control and session tools
may write ephemeral coordination state through the configured workspace intent
registry (file or SQLite backend) and optional audit records when enabled.

## Design rules

- **Codex-native packaging**: keep source under `plugins/` and publish the
  marketplace distribution through `orenlab/codeclone-codex`.
- **Canonical MCP first**: all analysis still flows through `codeclone-mcp`.
- **Skill guidance, not analysis logic**: the skill teaches conservative-first
  CodeClone review but does not create new findings.
- **No hidden installation side effects**: the plugin does not patch
  `~/.codex/config.toml`.
- **Source clarity**: the monorepo copy is the source; the public install
  surface is the `orenlab/codeclone-codex` distribution.
- **Launcher honesty**: the plugin assumes `codeclone-mcp` is already
  installable in the current workspace or reachable on `PATH`, and prefers the
  workspace environment when one is present.
- **Shell-free launch**: the bundled launcher must stay argv-based and
  local-stdio-only.

## Non-guarantees

- Codex plugin UI presentation may evolve independently of the plugin manifest
  content.
- Users who already configured `codeclone-mcp` manually may still prefer the
  direct MCP path over the bundled plugin MCP definition.

## Current limits

- If you already registered `codeclone-mcp` manually, keep only one setup path
  to avoid duplicate MCP surfaces.
- The bundled `.mcp.json` prefers `.venv`, then a Poetry env, then `PATH`.
- The bundled launcher stays shell-free and local-stdio-only.

## Further reading

- [MCP usage guide](../../guide/mcp/README.md)
- [MCP interface contract](../25-mcp-interface/index.md)
- [Engineering Memory](../13-engineering-memory/index.md)
- [Structural Change Controller](../12-structural-change-controller/index.md)
