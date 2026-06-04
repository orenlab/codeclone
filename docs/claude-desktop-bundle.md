<!-- doc-scope: SINGLE PAGE for Claude Desktop bundle — usage AND contract merged.
     owns: install, bundle workflow, settings, runtime model, design rules,
       non-guarantees.
     does-not-own: MCP contract (→ book/25), engineering memory (→ book/13).
     rule: replaces former guide + book/22 split. Do NOT re-split. -->
# Claude Desktop Bundle

Local `.mcpb` bundle wrapper for `codeclone-mcp` in
`extensions/claude-desktop-codeclone/`.

Installable package instead of hand-editing client JSON. Same canonical MCP
surface used by CLI, VS Code, Codex, and Claude Code. The manifest includes
pre-loaded instructions that guide Claude toward conservative-first,
production-first structural review.

!!! note "Wrapper only"
    The Claude Desktop bundle is a thin local launcher surface over
    `codeclone-mcp`. Analysis truth, findings, and health semantics remain in
    the canonical MCP server.

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
uv pip install --python .venv/bin/python "codeclone[mcp]"
.venv/bin/codeclone-mcp --help
```

Global fallback:

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

| Setting                        | Purpose                                                                                                     |
|--------------------------------|-------------------------------------------------------------------------------------------------------------|
| **Workspace root path**        | Optional absolute project root; launcher prefers that workspace `.venv` when Claude starts outside the repo |
| **CodeClone launcher command** | Absolute path or bare command for `codeclone-mcp`                                                           |
| **Advanced launcher args**     | JSON array of extra args (transport is always stdio)                                                        |

## Runtime model

Node wrapper launches `codeclone-mcp` via local `stdio`. It:

1. resolves a local `codeclone-mcp` launcher
2. validates advanced args
3. forces `--transport stdio`
4. launches the child process with `shell: false`
5. proxies stdio until shutdown

The wrapper prefers a workspace-local `.venv`, then a Poetry environment, then
user-local install paths, then `PATH`.

The bundle does **not** pass `--ide-governance-channel`. Agents see the standard
**31** MCP tools. VS Code session stats, audit trail webviews, and IDE Memory
governance (`prepare_governance` / `commit_governance`) require the VS Code
extension launcher.

Engineering Memory and optional semantic search follow the server contract in
[Engineering Memory](book/13-engineering-memory.md) (`query_engineering_memory`,
`get_relevant_memory`; semantic off by default in pyproject).

## Privacy

Local wrapper only — no telemetry, no cloud sync, no remote listener.
See [Privacy Policy](privacy-policy.md).

## Design rules

- **Canonical MCP first**: the bundle keeps Claude Desktop on the same
  documented MCP surface as other clients.
- **Local-only transport**: reject transport and remote-listener overrides.
- **Setup honesty**: fail with a bounded install hint when the launcher is
  missing.
- **No hidden runtime dependency games**: the bundle does not pretend to bundle
  Python or CodeClone itself.
- **Small and deterministic**: package only the wrapper, manifest, icon, and
  documentation needed for local installation.

## Non-guarantees

- Bundle presentation inside Claude Desktop may evolve with MCPB client UX.
- Auto-discovery heuristics for common launcher locations may evolve as long as
  the explicit launcher setting remains stable.
- The bundle does not guarantee automatic updates or remote install flows.

## Current limits

- expects either a workspace launcher, a user-local/global launcher, or an
  explicitly configured absolute launcher path
- local install surface, not a hosted service layer

## Source of truth

- CLI remains the scripting and CI surface.
- MCP remains the read-only agent/client contract.
- Claude Code can still register `codeclone-mcp` directly through `mcp add`.
- The Claude Desktop bundle is the installable local package layer for users
  who want a native Claude Desktop setup path.

For the underlying MCP contract, see
[MCP usage guide](mcp.md) and
[MCP interface contract](book/25-mcp-interface.md).
