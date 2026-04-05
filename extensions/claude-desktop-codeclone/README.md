# CodeClone for Claude Desktop

Local MCP bundle wrapper for `codeclone-mcp` — installs as a `.mcpb` package
instead of manual JSON editing.

Same canonical MCP surface used by CLI, VS Code, Codex, and Claude Code.
Read-only, baseline-aware, local stdio only.

## Install

```bash
uv tool install --pre "codeclone[mcp]"
codeclone-mcp --help                       # verify launcher
```

If you want to keep the launcher inside an existing environment instead, use:

```bash
uv pip install --pre "codeclone[mcp]"
```

Build and install the bundle:

```bash
cd extensions/claude-desktop-codeclone
node scripts/build-mcpb.mjs
```

Then in Claude Desktop: **Settings → Extensions → Install Extension** → select
the `.mcpb` from `dist/`.

If `codeclone-mcp` is not on `PATH`, set **CodeClone launcher command** in the
extension settings to an absolute path.

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
