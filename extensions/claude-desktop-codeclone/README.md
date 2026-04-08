# CodeClone for Claude Desktop

Local MCP bundle wrapper for `codeclone-mcp` — installs as a `.mcpb` package
instead of manual JSON editing.

Same canonical MCP surface used by CLI, VS Code, Codex, and Claude Code.
Read-only, baseline-aware, local stdio only.

## Install

The bundle prefers the current workspace launcher first:

1. `./.venv/bin/codeclone-mcp`
2. the current Poetry environment launcher
3. user-local install paths and `PATH`

Recommended workspace-local setup:

```bash
uv venv
uv pip install --python .venv/bin/python "codeclone[mcp]>=2.0.0b4"
.venv/bin/codeclone-mcp --help
```

Global fallback:

```bash
uv tool install "codeclone[mcp]>=2.0.0b4"
codeclone-mcp --help
```

Build and install the bundle:

```bash
cd extensions/claude-desktop-codeclone
node scripts/build-mcpb.mjs
```

Then in Claude Desktop: **Settings → Extensions → Install Extension** → select
the `.mcpb` from `dist/`.

If you want to bypass auto-discovery entirely, set **CodeClone launcher
command** in the extension settings to an absolute path.

## Configuration

| Setting                        | Purpose                                              |
|--------------------------------|------------------------------------------------------|
| **CodeClone launcher command** | Absolute path or bare command for `codeclone-mcp`    |
| **Advanced launcher args**     | JSON array of extra args (transport is always stdio) |

## Usage

```text
# Conservative first pass
Use CodeClone to analyze this repository and show the top production hotspots.

# Changed-files review
Use CodeClone for a changed-files review of my current diff.

# Deeper follow-up
Run a default CodeClone pass first. If clean, do a second higher-sensitivity pass.
```

## Privacy

Local wrapper only — no telemetry, no cloud sync, no remote listener.
See [Privacy Policy](https://orenlab.github.io/codeclone/privacy-policy/).

## Development

```bash
npm run check    # syntax check all JS
npm test         # run tests
npm run pack     # build .mcpb
```

## Links

- [Claude Desktop bundle guide](https://orenlab.github.io/codeclone/claude-desktop-bundle/)
- [MCP usage guide](https://orenlab.github.io/codeclone/mcp/)
- [Issues](https://github.com/orenlab/codeclone/issues)
