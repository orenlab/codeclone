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

The bundle starts only a trusted launcher, in this order:

1. the **CodeClone launcher command** from the bundle settings (an absolute path,
   or a bare name looked up in absolute `PATH` directories)
2. user-level install paths (`~/.local/bin`, `~/Library/Python/*/bin`, the
   Windows per-user Python `Scripts` directories)
3. `codeclone-mcp` from an absolute `PATH` directory

Opening a project is not consent to run programs from it: the bundle never
starts a launcher from the opened workspace (`.venv`, `venv`, an ancestor's
virtualenv, a Poetry environment, or a relative `PATH` entry).

Recommended setup:

```bash
uv tool install "codeclone[mcp]"
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

Node wrapper launches `codeclone-mcp` via local `stdio`: the configured launcher
command, else a user-level install path, else an absolute `PATH` entry. It never
starts a launcher from the opened workspace. To use a project virtual
environment, set **CodeClone launcher command** to the absolute path of its
`codeclone-mcp`.

## Privacy

Local wrapper only — no telemetry, no cloud sync, no remote listener.
See [Privacy Policy](privacy-policy.md).

## Current limits

- expects a user-level/global launcher or an explicitly configured launcher;
  a workspace `.venv` launcher is used only when configured by absolute path
- local install surface, not a hosted service layer

For the underlying MCP contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
