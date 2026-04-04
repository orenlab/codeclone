# CodeClone for Codex

CodeClone ships a native Codex plugin in `plugins/codeclone/`.

This plugin is a local Codex discovery and guidance layer over the canonical
`codeclone-mcp` server. It does not install Python, bundle CodeClone, or
invent a second analysis model.

## What ships here

- `.codex-plugin/plugin.json` for Codex plugin metadata
- `.mcp.json` for the local `codeclone-mcp --transport stdio` definition
- `skills/codeclone-review/` for conservative-first CodeClone review guidance
- `assets/` for plugin branding

## What it is for

Use this plugin when you want a native Codex surface for CodeClone instead of
registering `codeclone-mcp` manually.

It keeps Codex on the same:

- MCP tools and resources
- baseline-aware semantics
- triage-first review model
- conservative-first analysis profile guidance

## Runtime model

The plugin stays thin on purpose:

- Codex discovers the plugin from `.agents/plugins/marketplace.json`
- the plugin contributes a local `.mcp.json` server definition
- the plugin skill teaches Codex how to use CodeClone MCP well

It does not rewrite `~/.codex/config.toml` and does not mutate repository
state.

## Install notes

- `codeclone-mcp` must already be installed and resolvable on `PATH`, or
  registered separately through user config
- if you already added CodeClone manually with `codex mcp add`, you may want
  to keep only one setup path to avoid duplicate MCP surfaces

Manual MCP registration remains valid:

```bash
codex mcp add codeclone -- codeclone-mcp --transport stdio
```

## Source of truth

The plugin is only a Codex-native shell over the same canonical CodeClone
contracts used everywhere else.

- docs: <https://orenlab.github.io/codeclone/codex-plugin/>
- MCP guide: <https://orenlab.github.io/codeclone/mcp/>
- privacy: <https://orenlab.github.io/codeclone/privacy-policy/>
- terms: <https://orenlab.github.io/codeclone/terms-of-use/>
