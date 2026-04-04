# Codex Plugin

CodeClone ships a native Codex plugin in `plugins/codeclone/`.

This is the Codex-native surface for CodeClone. It uses the local plugin model
instead of pretending Codex wants a VS Code-style extension package.

## What it is for

The plugin gives Codex:

- a repo-local discoverable plugin entry
- a local MCP server definition for `codeclone-mcp`
- a focused CodeClone review skill
- starter prompts aligned with the canonical CodeClone workflow

It stays read-only and does not create a second analysis model.

## What ships in the plugin

- `.codex-plugin/plugin.json` for plugin metadata and prompts
- `.mcp.json` for the local `codeclone-mcp --transport stdio` definition
- `skills/codeclone-review/SKILL.md` for conservative-first, triage-first usage
  guidance
- `.agents/plugins/marketplace.json` for repo-local plugin discovery

## Runtime model

The plugin is additive:

- Codex can discover the plugin from `.agents/plugins/marketplace.json`
- the plugin contributes a local MCP definition
- the skill teaches Codex how to use the existing CodeClone MCP surface well

The plugin does not mutate `~/.codex/config.toml` and does not install a second
server binary.

## Relationship to `codex mcp add`

Codex already supports direct MCP registration:

```bash
codex mcp add codeclone -- codeclone-mcp --transport stdio
```

That path remains valid and is still the simplest manual setup.

The plugin exists for the native Codex plugin/discovery surface:

- plugin card metadata
- local marketplace entry
- bundled CodeClone review skill
- repo-local MCP definition

## Product decisions

- **Codex-native path**: use the local plugin system for discovery and skills
- **Canonical MCP first**: the plugin points to the same `codeclone-mcp`
  server and semantics as every other client
- **Skill-guided review**: the plugin adds workflow guidance, not a second
  analyzer
- **No hidden config writes**: the plugin does not rewrite user MCP config

## Current limits

- if you already registered `codeclone-mcp` manually in `~/.codex/config.toml`,
  you may see a duplicate Codex MCP surface until you keep only one setup path
- the bundled `.mcp.json` assumes `codeclone-mcp` resolves on `PATH`
- explicit launcher overrides still belong in user config, not inside the
  plugin manifest

## Source of truth

The Codex plugin is only a local presentation and discovery layer over:

- `codeclone-mcp`
- the canonical report semantics behind MCP
- the existing CodeClone docs and contracts

For the underlying interface contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
