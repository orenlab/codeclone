# CodeClone for Claude Desktop

Structural change controller for Python — local MCP bundle wrapper for
`codeclone-mcp`. Installs as a `.mcpb` package instead of manual JSON editing.

Same canonical 28-tool MCP surface used by CLI, VS Code, Codex, and Claude Code.
Read-only, baseline-aware, local stdio only.
As the local `codeclone-mcp` server gains new canonical surfaces, the bundle
exposes them without adding a second client-side interpretation layer.

## Install

The bundle prefers the current workspace launcher first:

1. `./.venv/bin/codeclone-mcp`
2. the current Poetry environment launcher
3. user-local install paths and `PATH`

Recommended workspace-local setup:

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

### Change controller workflow

```text
# 1. Analyze the repository
Use CodeClone to analyze this repository.

# 2. Declare intent before editing
Declare a change intent for refactoring codeclone/core/parser.py — I plan to
extract the CFG builder into a separate module.

# 3. Check blast radius
Show the blast radius for codeclone/core/parser.py.

# 4. After editing — verify the patch
Check my change intent against the current diff.

# 5. Generate the audit artifact
Create a review receipt for the verified change.
```

### Analysis and review

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
- [Change controller docs](https://orenlab.github.io/codeclone/book/24-structural-change-controller/)
- [Issues](https://github.com/orenlab/codeclone/issues)
