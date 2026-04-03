# CodeClone for VS Code

CodeClone for VS Code is a native IDE surface for `codeclone-mcp`.

It brings CodeClone's baseline-aware structural analysis into the editor without
creating a second truth model. The extension stays read-only with respect to
repository state and uses the same canonical report semantics as the CLI, HTML
report, and MCP server.

This extension is published as a preview while the `2.0.0b4` line is still in
beta.

## What it is for

CodeClone inside VS Code is designed for:

- triage-first structural review
- changed-files review against the current diff
- baseline-aware distinction between known debt and new regressions
- guided drill-down from hotspot to source, finding detail, and remediation

It is not a generic linter panel and it does not try to duplicate the HTML
report inside the sidebar.

## Product principles

- **Canonical-report-first**: IDE views are projections over the same report
  truth exposed by CodeClone.
- **Baseline-aware**: the extension prefers new and relevant findings over
  broad full-repository listing.
- **Triage-first**: the default path is review, not enumeration.
- **Read-only**: the extension does not edit source files, baselines, caches,
  or report artifacts.
- **Guided**: the extension should make the cheapest useful path the most
  obvious path.

## Install

CodeClone for VS Code needs a local `codeclone-mcp` launcher.

Recommended install for the preview extension:

```bash
pip install --pre "codeclone[mcp]"
```

After the `2.0.0b4` line is stable, the regular install command is enough:

```bash
pip install "codeclone[mcp]"
```

Verify the launcher:

```bash
codeclone-mcp --help
```

## First run

1. Open a trusted Python workspace.
2. Open the `CodeClone` view container.
3. Run `Analyze Workspace`.
4. Use `Review Priorities` or `Review Changes` as the first pass.

If the local launcher is missing, use `Setup Help` from the view or command
palette.

## Main surfaces

### Overview

Compact repository health, current run state, and next-best review action.

### Hotspots

The main operational view. It focuses on:

- new regressions
- production hotspots
- changed-files findings
- report-only God Module candidates

### Runs & Session

Bounded MCP session state:

- local server availability
- current run identity
- reviewed findings
- help topics

Reviewed markers are session-local only and do not mutate the repository or the
canonical report.

## Interaction model

The extension is intentionally code-centered:

- findings prefer `Reveal Source` as the default review action
- source locations are opened in the editor and softly highlighted
- deeper actions stay explicit:
    - `Open Finding`
    - `Show Remediation`
    - `Mark Reviewed`

This keeps the extension focused on review and refactoring flow instead of
opening raw JSON-like details by default.

## Settings

### `codeclone.mcp.command`

Launcher used to start the local CodeClone server. Leave it as `auto` for the
default behavior.

### `codeclone.mcp.args`

Extra arguments passed to the configured launcher.

### `codeclone.analysis.cachePolicy`

Default cache policy for analysis requests.

### `codeclone.analysis.changedDiffRef`

Git revision used by `Review Changes`.

### `codeclone.ui.showStatusBar`

Show or hide the workspace-level status bar item.

## Trust and workspace model

This extension runs structural analysis against the current repository and uses
local filesystem and git state. For that reason:

- untrusted workspaces are not supported
- virtual workspaces are not supported
- the extension runs as a workspace extension

## Source of truth

The extension is a client over `codeclone-mcp`.

It does not:

- recompute findings independently
- redefine health semantics
- mutate the repository
- rewrite baselines or reports

If you need the contract-level documentation behind the extension behavior, see:

- [CodeClone documentation](https://orenlab.github.io/codeclone/)
- [MCP usage guide](https://orenlab.github.io/codeclone/mcp/)
- [MCP interface contract](https://orenlab.github.io/codeclone/book/20-mcp-interface/)

## Development

Open this folder in VS Code and press `F5` to run an Extension Development
Host.

Useful local checks:

```bash
node --check src/mcpClient.js
node --check src/extension.js
```
