<!-- doc-scope: Claude Desktop bundle setup. class: guide max-lines: 160 -->

# Claude Desktop setup

Local `.mcpb` bundle that launches `codeclone-mcp` over stdio. Same canonical MCP
surface as CLI, VS Code, Codex, and Cursor — no second analyzer or truth path.

For the terminal agent, use the separate
[Claude Code marketplace plugin](../claude-code/setup.md). The `.mcpb` described
here is only for Claude Desktop.

## Prerequisites

- Claude Desktop with extension support
- Node.js (to build the bundle from source)
- Python 3.10+ with `codeclone[mcp]` installed

## Install the MCP launcher

The bundle prefers the current workspace launcher first:

1. `./.venv/bin/codeclone-mcp`
2. the current Poetry environment launcher
3. user-local install paths and `PATH`

Workspace-local setup:

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

## Build and install the `.mcpb` bundle

From the repository:

```bash
cd extensions/claude-desktop-codeclone
node scripts/build-mcpb.mjs
```

In Claude Desktop: **Settings → Extensions → Install Extension** → select the
`.mcpb` from `dist/`.

To bypass auto-discovery, set **CodeClone launcher command** in extension settings
to an absolute path to `codeclone-mcp`.

## Configuration

| Setting                        | Purpose                                                                 |
|--------------------------------|-------------------------------------------------------------------------|
| **Workspace root path**        | Optional absolute project root; launcher prefers that workspace `.venv` |
| **CodeClone launcher command** | Absolute path or bare command for `codeclone-mcp`                       |
| **Advanced launcher args**     | JSON array of extra args (transport is always stdio)                    |

## Read-only vs coordination writes

The MCP server never mutates repository source, baselines, analysis cache, or
canonical reports. It may write ephemeral coordination state under
`.codeclone/intents/` (file backend) or `.codeclone/db/intents.sqlite3`
(SQLite backend), optional audit records when enabled, and Engineering
Memory **draft** rows through agent tools. Human approve/reject stays in VS Code
Memory or `codeclone memory approve --i-know-what-im-doing` (optional `--by NAME`).

## First workflow

```text
1. Use CodeClone to analyze this repository.
2. Declare a change intent before editing (start_controlled_change).
3. Show blast radius for the files you plan to change.
4. Edit within declared scope.
5. Finish the change intent with changed_files evidence.
```

Recipe pages: [MCP workflows](../../mcp/workflows/change-control.md),
[Change controller](../../../book/12-structural-change-controller/index.md).

## Privacy

Local wrapper only — no telemetry, no cloud sync, no remote listener.
See [Privacy Policy](https://orenlab.github.io/codeclone/privacy-policy/).

## Development smoke

```bash
cd extensions/claude-desktop-codeclone
npm run check
npm test
npm run pack
```

Contract reference: [Claude Desktop bundle](../../../book/integrations/claude-desktop-bundle.md).
