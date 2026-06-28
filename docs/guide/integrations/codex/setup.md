# Codex setup

Contract: [Codex plugin](../../../book/integrations/codex-plugin.md).

## Install

Install the plugin from the Codex marketplace:

```bash
codex plugin marketplace add orenlab/codeclone-codex
codex plugin add codeclone@orenlab-codeclone
```

The first command registers the public marketplace repository. The second
installs the `codeclone` plugin from the marketplace named
`orenlab-codeclone`.

Verify the configured marketplace and installed plugin:

```bash
codex plugin marketplace list
codex plugin list
```

The plugin manifest version tracks the CodeClone package release line (currently
`2.1.0a1` in this monorepo). It describes the bundled guidance surface, not the
live MCP tool count — tools come from the resolved `codeclone-mcp` server.

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

### codeclone-engineering-memory

Scope-aware Engineering Memory over MCP: `get_relevant_memory` (absolute
`root` required), `query_engineering_memory`, draft `record_candidate`, and
`finish(..., propose_memory=true)`. Complements change control — does not replace
intent declaration or patch verify. Human approve stays in the CodeClone VS Code
**Memory** view (not MCP).

Optional **semantic search**: off by default in
`[tool.codeclone.memory.semantic]`; when enabled, install
`codeclone[semantic-local]` for local semantic-quality recall (or
`codeclone[semantic-lancedb]` for the diagnostic sidecar only), rebuild the index, then
`query_engineering_memory(mode=search, semantic=true)`. Default provider
`diagnostic` is deterministic, not semantic-quality embeddings; set
`embedding_provider = "fastembed"` for FastEmbed. See
[Engineering Memory](../../../book/13-engineering-memory/index.md).
