# VS Code Extension

CodeClone ships a preview VS Code extension in
`extensions/vscode-codeclone/`.

It is a native IDE surface over `codeclone-mcp` and is designed for
baseline-aware, triage-first structural review inside the editor.

## What it does

The extension helps you:

- analyze the current workspace
- review changed files against a git diff
- focus on new regressions and production hotspots first
- jump directly to source locations
- open canonical finding or remediation detail only when needed

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

Compact health, current run state, and next-best review action.

### Hotspots

Primary operational view for:

- new regressions
- production hotspots
- changed-files findings
- report-only God Module candidates

### Runs & Session

Session-local state:

- local server availability
- current run identity
- reviewed findings
- MCP help topics

## First-run path

1. Open the `CodeClone` view container.
2. Run `Analyze Workspace`.
3. Use `Review Priorities` or `Review Changes`.
4. Reveal source before opening deeper detail.

If the launcher is missing, use `Setup Help` from the extension.

## Trust model

The extension requires a trusted local workspace and is not intended for
virtual workspaces.

That is intentional: CodeClone reads repository contents, local git state, and
the local MCP launcher.

## Source of truth

The extension reads the same canonical analysis semantics already exposed by:

- CodeClone CLI
- canonical report JSON
- CodeClone MCP

For the underlying interface contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [VS Code extension contract](book/21-vscode-extension.md)
