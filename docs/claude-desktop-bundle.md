# Claude Desktop Bundle

Local `.mcpb` bundle wrapper for `codeclone-mcp` in
`extensions/claude-desktop-codeclone/`.

Installable package instead of hand-editing client JSON. Same canonical MCP
surface used by CLI, VS Code, Codex, and Claude Code. The manifest includes
pre-loaded instructions that guide Claude toward conservative-first,
production-first structural review.

## Install

```bash
uv tool install "codeclone[mcp]"    # or: uv pip install "codeclone[mcp]"
codeclone-mcp --help                # verify
```

## Bundle workflow

1. Build: `cd extensions/claude-desktop-codeclone && node scripts/build-mcpb.mjs`
2. Claude Desktop: **Settings → Extensions → Install Extension** → select `.mcpb`
3. If `codeclone-mcp` is not on `PATH`, set **CodeClone launcher command** in
   the bundle settings to an absolute path.

## Settings

| Setting                        | Purpose                                              |
|--------------------------------|------------------------------------------------------|
| **CodeClone launcher command** | Absolute path or bare command for `codeclone-mcp`    |
| **Advanced launcher args**     | JSON array of extra args (transport is always stdio) |

## Runtime model

Node wrapper launches `codeclone-mcp` via local `stdio`. Auto-discovers the
launcher in `~/.local/bin`, macOS `~/Library/Python/*/bin`, or Windows Python
paths. Falls back to `PATH`.

## Privacy

Local wrapper only — no telemetry, no cloud sync, no remote listener.
See [Privacy Policy](privacy-policy.md).

## Current limits

- expects a global or explicitly configured launcher
- local install surface, not a hosted service layer

For the underlying MCP contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
