# 23. Codex Plugin

## Purpose

Document the current contract and behavior of the Codex plugin shipped in
`plugins/codeclone/`.

This chapter describes the plugin as a local Codex discovery and guidance layer
over existing CodeClone MCP contracts.

## Position in the platform

The Codex plugin is:

- a repo-local Codex plugin under `plugins/`
- backed by `.agents/plugins/marketplace.json`
- read-only with respect to repository state
- a composition of local MCP server metadata plus Codex skill guidance
- a native Codex setup surface, not a second extension model

## Source of truth

The plugin delegates analysis to the existing `codeclone-mcp` launcher and
guides usage through a plugin-bundled skill.

It must not:

- run a second analysis engine
- redefine findings, health, or gates
- mutate source files, baselines, cache, or report artifacts
- drift away from canonical MCP semantics

## Current surface

The plugin currently provides:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `README.md`
- one bundled skill:
    - `codeclone-review`
- a repo-local marketplace entry in `.agents/plugins/marketplace.json`

## Runtime model

The plugin surface is additive:

- `.mcp.json` contributes a local stdio MCP server definition
- the skill contributes workflow guidance and starter prompts
- `README.md` documents local usage and boundaries inside the repository tree
- Codex remains free to use direct `mcp add` config alongside or instead of the
  plugin

The plugin does not rewrite user config or install CodeClone automatically.

## Design rules

- **Codex-native packaging**: use `plugins/` plus `.agents/plugins/marketplace.json`
  for discovery.
- **Canonical MCP first**: all analysis still flows through `codeclone-mcp`.
- **Skill guidance, not analysis logic**: the skill teaches conservative-first
  CodeClone review but does not create new findings.
- **No hidden installation side effects**: the plugin does not patch
  `~/.codex/config.toml`.
- **Repo-local clarity**: the plugin is meant to travel with the repository as
  a native Codex surface.
- **Launcher honesty**: the plugin assumes `codeclone-mcp` is already
  installable or configured in the local environment.

## Relationship to other interfaces

- CLI remains the scripting and CI surface.
- MCP remains the cross-client integration contract.
- `codex mcp add` remains a valid manual setup path.
- The Codex plugin is the native Codex discovery and guidance layer for
  CodeClone.

## Non-guarantees

- Codex plugin UI presentation may evolve independently of the plugin manifest
  content.
- Users who already configured `codeclone-mcp` manually may still prefer the
  direct MCP path over the bundled plugin MCP definition.
