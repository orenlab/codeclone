# VS Code Extension

CodeClone ships a preview VS Code extension in
`extensions/vscode-codeclone/`.

It is a native IDE surface over `codeclone-mcp` and is designed for
baseline-aware, triage-first structural review inside the editor.

## What it is for

The extension helps you:

- analyze the current workspace
- review changed files against a git diff
- start with a conservative first pass and lower thresholds only when you need
  a more sensitive follow-up
- focus on new regressions and production hotspots first
- jump directly to source locations
- open canonical finding or remediation detail only when needed
- inspect report-only Overloaded Module candidates without treating them like findings

It does not create a second truth model and it does not mutate the repository.

## Install requirements

The extension needs a local `codeclone-mcp` launcher.

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

## Main views

### Overview

Compact health, current run state, baseline drift, and next-best review action.

### Hotspots

Primary operational view for:

- new regressions
- production hotspots
- changed-files findings
- report-only Overloaded Module candidates

### Runs & Session

Session-local state:

- local server availability
- current run identity
- reviewed findings
- MCP help topics

## Review model

The extension stays source-first:

- `Review Priorities` and `Next Hotspot` / `Previous Hotspot` drive the review
  loop
- `Reveal Source` is the default action for findings
- editor-local actions appear only when the current file matches the active
  review target
- Explorer decorations stay lightweight and focus on new, production, or
  changed-scope relevance

`Open in HTML Report` exists as an explicit bridge to the richer human report,
not as the primary IDE workflow.

## First-run path

1. Open the `CodeClone` view container.
2. Run `Analyze Workspace`.
3. Use `Review Priorities` or `Review Changes`.
4. If the first pass looks clean but you want smaller repeated units, open
   `Analysis Depth`.
5. Reveal source before opening deeper detail.

If the launcher is missing, use `Setup Help` from the extension.

## Trust model

The extension uses a **limited Restricted Mode**:

- onboarding and setup help remain available in untrusted workspaces
- local analysis and the local MCP server stay disabled until workspace trust
  is granted

The extension is not intended for virtual workspaces.

That is intentional: CodeClone reads repository contents, local git state, and
the local MCP launcher.

## Design decisions

- Native VS Code views first, not a custom report dashboard
- Baseline-aware review instead of broad lint-style listing
- Conservative first pass by default; deeper sensitivity is explicit

## Current limits

- no always-on background analysis
- no `Problems`-panel duplication
- no persistent reviewed markers across MCP sessions
- `Open in HTML Report` opens a local HTML report only when it exists and looks
  fresh enough for the current run

## Settings that shape analysis depth

- `codeclone.analysis.profile` keeps the default conservative first pass
  explicit and exposes `Deeper review` and `Custom` as deliberate follow-ups
- `codeclone.analysis.minLoc`
- `codeclone.analysis.minStmt`
- `codeclone.analysis.blockMinLoc`
- `codeclone.analysis.blockMinStmt`
- `codeclone.analysis.segmentMinLoc`
- `codeclone.analysis.segmentMinStmt`

Custom thresholds apply only when the profile is set to `custom`.

## Source of truth

The extension reads the same canonical analysis semantics already exposed by:

- CodeClone CLI
- canonical report JSON
- CodeClone MCP

For the underlying interface contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [VS Code extension contract](book/21-vscode-extension.md)
