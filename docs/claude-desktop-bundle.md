# Claude Desktop Bundle

Local `.mcpb` bundle wrapper for `codeclone-mcp` in
`extensions/claude-desktop-codeclone/`.

Installable package instead of hand-editing client JSON. Same canonical MCP
surface used by CLI, VS Code, Codex, and Claude Code. The manifest includes
pre-loaded instructions that guide Claude toward conservative-first,
production-first structural review.

Because the bundle is only a launcher wrapper, newly added canonical MCP
surfaces from the local `codeclone-mcp` version flow through directly,
including current-run `Coverage Join` facts and the optional `coverage` help
topic when supported by that server.

## Install

The bundle prefers the current workspace launcher first:

1. `./.venv/bin/codeclone-mcp`
2. the current Poetry environment launcher
3. user-local install paths and `PATH`

```bash
uv venv
uv pip install --python .venv/bin/python "codeclone[mcp]>=2.0.0b5"
.venv/bin/codeclone-mcp --help
```

Global fallback:

```bash
uv tool install "codeclone[mcp]>=2.0.0b5"
codeclone-mcp --help
```

## Bundle workflow

1. Build: `cd extensions/claude-desktop-codeclone && node scripts/build-mcpb.mjs`
2. Claude Desktop: **Settings → Extensions → Install Extension** → select `.mcpb`
3. If you want to bypass auto-discovery, set **CodeClone launcher command** in
   the bundle settings to an absolute path.

## Settings

| Setting                        | Purpose                                              |
|--------------------------------|------------------------------------------------------|
| **CodeClone launcher command** | Absolute path or bare command for `codeclone-mcp`    |
| **Advanced launcher args**     | JSON array of extra args (transport is always stdio) |

## Runtime model

Node wrapper launches `codeclone-mcp` via local `stdio`. It prefers a
workspace-local `.venv`, then a Poetry environment, then user-local install
paths, then `PATH`.

## Privacy

Local wrapper only — no telemetry, no cloud sync, no remote listener.
See [Privacy Policy](privacy-policy.md).

## Current limits

- expects either a workspace launcher, a user-local/global launcher, or an
  explicitly configured absolute launcher path
- local install surface, not a hosted service layer

For the underlying MCP contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
