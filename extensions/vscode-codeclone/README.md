# CodeClone for VS Code

CodeClone for VS Code is a native IDE surface for `codeclone-mcp`.

Marketplace: [CodeClone for VS Code](https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone)

It brings CodeClone's baseline-aware structural analysis into the editor without
creating a second truth model. The extension stays read-only with respect to
repository state and uses the same canonical report semantics as the CLI, HTML
report, and MCP server.

This extension is published as a preview while the `2.0.0b5` line is still in
beta.

## What it is for

CodeClone inside VS Code is designed for:

- triage-first structural review
- changed-files review against the current diff
- conservative first-pass analysis with an explicit deeper-review follow-up
- baseline-aware distinction between known debt and new regressions
- guided drill-down from hotspot to source, finding detail, and remediation
- lightweight code navigation without turning the sidebar into a second report app

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

Minimum supported CodeClone version: `2.0.0b4`.

In `auto` mode, the extension checks the current workspace virtualenv before
falling back to `PATH`. Runtime and version-mismatch messages identify that resolved launcher source.

Recommended install for the preview extension:

```bash
uv tool install "codeclone[mcp]>=2.0.0b4"
```

If you want the launcher inside the current environment instead:

```bash
uv pip install "codeclone[mcp]>=2.0.0b4"
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
5. If the first pass looks clean but you want smaller repeated units, open
   `Set Analysis Depth`.

If the local launcher is missing, use `Open Setup Help` from the view or command
palette.

## Main surfaces

### Overview

Compact repository health, current run state, baseline drift, and next-best
review action.

### Hotspots

The main operational view. It focuses on:

- new regressions
- production hotspots
- changed-files findings
- report-only Overloaded Module candidates

Focus mode is explicit and persisted per workspace. The extension favors
`Recommended` by default and keeps report-only candidates visually separate from
findings.

### Runs & Session

Bounded MCP session state:

- local server availability
- current run identity
- reviewed findings
- help topics

Reviewed markers are session-local only and do not mutate the repository or the
canonical report.

### Editor interaction

- `Reveal Source` is the default review action for findings
- active review targets can be stepped with `Next Hotspot` / `Previous Hotspot`
- review-relevant files receive lightweight Explorer decorations
- CodeLens and editor-title actions appear only when the current editor matches
  the active review target
- `Open in HTML Report` is available as an explicit bridge, not as the primary
  review surface

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

## Product decisions

- **Native VS Code first**: tree views, status bar, file decorations, and
  editor actions come before any richer custom surface.
- **No second truth model**: health, findings, and drift come from CodeClone
  MCP and canonical report semantics only.
- **Source-first**: review should move you to code before it opens deeper
  detail.
- **Report-only separation**: `Overloaded Modules` are visible but intentionally kept
  outside findings, gates, and health.
- **Limited Restricted Mode**: the extension keeps setup/onboarding available in
  untrusted workspaces, but local analysis and MCP stay disabled until trust is
  granted.

## Current limits

- The extension does not run background analysis on every save.
- It does not populate VS Code Problems or try to behave like a linter.
- Reviewed markers are session-local only.
- `Open in HTML Report` only uses a local `report.html` when one already exists
  and looks fresh enough for the current run.
- Virtual workspaces are not supported.

## Settings

### `codeclone.mcp.command`

Launcher used to start the local CodeClone server. Leave it as `auto` for the
default behavior. This is a machine-scoped setting, so it belongs in user or
remote settings rather than workspace settings.

### `codeclone.mcp.args`

Extra arguments passed to the configured launcher. This is also machine-scoped.

### `codeclone.analysis.cachePolicy`

Default cache policy for analysis requests. Analysis settings are resource-scoped,
so they can differ per workspace or folder.

### `codeclone.analysis.changedDiffRef`

Git revision used by `Review Changes`.

### `codeclone.analysis.profile`

Keeps the default conservative pass explicit and exposes `Deeper review` or
`Custom` only as deliberate higher-sensitivity follow-ups.

### `codeclone.analysis.minLoc` and related threshold settings

Function, block, and segment thresholds used only when
`codeclone.analysis.profile` is set to `custom`.

### `codeclone.ui.showStatusBar`

Show or hide the workspace-level status bar item for the current VS Code window.

## Trust and workspace model

This extension runs structural analysis against the current repository and uses
local filesystem and git state. For that reason:

- untrusted workspaces are supported only in a limited onboarding/setup mode
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
node --check src/support.js
node --check src/mcpClient.js
node --check src/extension.js
node --test test/*.test.js
node test/runExtensionHost.js
```
