# Claude Desktop Bundle

CodeClone ships a local Claude Desktop bundle in
`extensions/claude-desktop-codeclone/`.

It is a small Node-based `.mcpb` wrapper around the local `codeclone-mcp`
launcher.

## What it is for

The bundle exists to make local CodeClone setup in Claude Desktop easier:

- installable `.mcpb` package instead of hand-editing client JSON
- the same read-only `codeclone-mcp` surface already used by other MCP clients
- explicit local-stdio runtime
- optional launcher override when `codeclone-mcp` is not already on `PATH`

It does not bundle Python or CodeClone itself.

## Install requirements

Install CodeClone with the optional MCP extra first:

```bash
uv tool install "codeclone[mcp]"
```

You can also use:

```bash
pip install "codeclone[mcp]"
```

Verify the launcher:

```bash
codeclone-mcp --help
```

## Bundle workflow

1. Build the `.mcpb` package from `extensions/claude-desktop-codeclone/`.
2. In Claude Desktop, open `Settings -> Extensions -> Advanced settings`.
3. Install the generated `.mcpb`.
4. If Claude Desktop cannot resolve `codeclone-mcp`, set an explicit launcher
   command in the bundle settings.

## Runtime model

The bundle runs a small Node wrapper that launches `codeclone-mcp` via local
`stdio`. Claude Desktop talks to the same canonical MCP surface as every other
client — the bundle only handles launcher resolution.

## Settings

### `CodeClone launcher command`

Optional absolute path or bare command name for `codeclone-mcp`.

### `Advanced launcher args (JSON array)`

Optional JSON array of additional launcher arguments for advanced setups.

The bundle rejects transport and network-listener arguments because the Claude
Desktop package is intentionally local-stdio-only.

## Design decisions

- **Small wrapper, not a shadow runtime** — Node only locates and launches
  `codeclone-mcp`
- **Setup honesty** — missing launchers fail with a clear install hint
- **Local-only transport** — no streamable HTTP or remote-listener switches

## Privacy

Local wrapper only — no telemetry, no cloud sync, no remote listener.
See [Privacy Policy](privacy-policy.md).

## Current limits

- the bundle expects a global or explicitly configured launcher; it does not
  auto-discover repository-local virtual environments
- it is a local install surface for Claude Desktop, not a hosted service layer
- it does not change CodeClone MCP semantics or add bundle-only tools

For the underlying MCP contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
