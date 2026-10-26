# CodeClone for Claude Desktop

Local MCP bundle wrapper for `codeclone-mcp` — installs as a `.mcpb` package
instead of manual JSON editing.

Same canonical MCP surface used by CLI, VS Code, Codex, and Claude Code.
Read-only, baseline-aware, local stdio only.
As the local `codeclone-mcp` server gains new canonical surfaces, the bundle
exposes them without adding a second client-side interpretation layer.

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

# Coverage-aware follow-up
If the current run includes coverage data, explain the Coverage Join facts and any scope gaps.
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
