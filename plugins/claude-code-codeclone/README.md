# CodeClone for Claude Code

Native Claude Code plugin for the CodeClone **Structural Change Controller**.
It connects Claude Code to the same local `codeclone-mcp` server used by the
CLI, Codex, Cursor, VS Code, and Claude Desktop.

## Install

Add the public marketplace and install CodeClone:

```bash
claude plugin marketplace add orenlab/codeclone-claude-code
claude plugin install codeclone@orenlab-codeclone
```

Inside an interactive Claude Code session, the equivalent commands are:

```text
/plugin marketplace add orenlab/codeclone-claude-code
/plugin install codeclone@orenlab-codeclone
```

Install the local MCP server separately:

```bash
uv tool install --prerelease allow "codeclone[mcp]"
codeclone-mcp --help
```

For a workspace-local environment:

```bash
uv venv
uv pip install --prerelease allow --python .venv/bin/python "codeclone[mcp]"
.venv/bin/codeclone-mcp --help
```

The launcher prefers a workspace `.venv`, then the current Poetry environment,
then `codeclone-mcp` from `PATH`. It uses local stdio and does not rewrite
Claude Code settings.

## Skills

Claude Code namespaces plugin skills with the plugin name:

| Skill | Invocation |
|---|---|
| Repository review | `/codeclone:codeclone-review` |
| Hotspot snapshot | `/codeclone:codeclone-hotspots` |
| Controlled repository edit | `/codeclone:codeclone-change-control` |
| Engineering Memory | `/codeclone:codeclone-engineering-memory` |
| Implementation context | `/codeclone:codeclone-implementation-context` |
| Platform Observability (maintainer-only) | `/codeclone:codeclone-platform-observability` |

The MCP server remains read-only with respect to source, baselines, cache, and
canonical reports. Change control, audit, and Engineering Memory write only
their documented bounded local state.

## Development

Load the monorepo source directly:

```bash
claude --plugin-dir plugins/claude-code-codeclone
```

Validate the plugin:

```bash
claude plugin validate plugins/claude-code-codeclone
```

## Documentation

- [Claude Code setup](https://orenlab.github.io/codeclone/guide/integrations/claude-code/setup/)
- [MCP usage guide](https://orenlab.github.io/codeclone/guide/mcp/)
- [Structural Change Controller](https://orenlab.github.io/codeclone/book/12-structural-change-controller/)
