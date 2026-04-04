# CodeClone for Claude Desktop

CodeClone for Claude Desktop is a small MCP bundle wrapper for the local
`codeclone-mcp` launcher.

It exists to make CodeClone easy to install in Claude Desktop without asking
users to hand-edit MCP JSON. The bundle stays read-only, keeps Claude on the
same canonical CodeClone MCP surface, and does not create a second analysis
model.

## Description

This bundle gives Claude Desktop a native install surface for local CodeClone
MCP usage.

It is intended for people who want:

- a local `.mcpb` install instead of manual connector JSON
- the same canonical CodeClone MCP tools already used by CLI, Codex, Claude
  Code, and VS Code
- a conservative-first structural review workflow without introducing a second
  analysis model inside Claude Desktop

## Features

- starts a local `codeclone-mcp` process in `stdio` mode
- keeps transport local and read-only
- lets users configure an explicit launcher command when `codeclone-mcp` is not
  already on `PATH`
- preserves the same baseline-aware, canonical-report-first behavior already
  exposed by CodeClone CLI, HTML, MCP, and the VS Code extension
- keeps launcher configuration intentionally narrow and local-only

## Limits

- it does not bundle Python or CodeClone itself
- it does not mutate source files, baselines, cache, or report artifacts
- it does not reinterpret findings or add extension-only analysis semantics
- it does not provide a remote listener or hosted service path

## Installation

Install CodeClone with the optional MCP extra first:

```bash
uv tool install "codeclone[mcp]"
```

You can also use:

```bash
pip install "codeclone[mcp]"
```

Verify the launcher:

```bash
codeclone-mcp --help
```

Build the bundle:

```bash
cd extensions/claude-desktop-codeclone
node scripts/build-mcpb.mjs
```

Then install it in Claude Desktop:

1. Build the `.mcpb` bundle from this folder.
2. Open Claude Desktop.
3. Go to `Settings -> Extensions -> Advanced settings -> Install Extension...`.
4. Select the generated `.mcpb` file.
5. If `codeclone-mcp` is not already on `PATH`, open the extension settings and
   set `CodeClone launcher command` to an absolute path or a bare command name
   that resolves correctly in Claude Desktop.

## Configuration

### `CodeClone launcher command`

Optional. Use this when Claude Desktop cannot resolve `codeclone-mcp` from
`PATH`.

Recommended values:

- `/Users/you/.local/bin/codeclone-mcp`
- `codeclone-mcp`

### `Advanced launcher args (JSON array)`

Optional. This is intentionally narrow and meant only for advanced local
launchers. The value must be a JSON array of strings.

Example:

```json
["--history-limit", "4"]
```

Do not add `--transport` here. The bundle always uses local `stdio`.

## Examples

### 1. Conservative first pass

```text
Use CodeClone to analyze this repository and give me a compact structural health
summary. Start with the default profile and show me the most important production
hotspots first.
```

### 2. Changed-files review

```text
Use CodeClone for a changed-files review of my current work. Focus only on
findings that touch changed files and rank them by priority.
```

### 3. Deeper exploratory follow-up

```text
Run a default CodeClone pass first. If it looks clean, do a second,
higher-sensitivity exploratory pass with lower thresholds and explain which
smaller local repetitions are worth investigating.
```

## Privacy Policy

CodeClone is a local analysis tool and this bundle is a local wrapper around
`codeclone-mcp`.

- the bundle does not run its own telemetry service
- the bundle does not upload repository contents to a CodeClone backend
- the bundle only launches the local `codeclone-mcp` process and proxies local
  `stdio`
- repository access happens locally through CodeClone MCP when you ask Claude to
  analyze code

Bundle privacy details:

- [CodeClone Privacy Policy](https://orenlab.github.io/codeclone/privacy-policy/)

## Support

- GitHub issues: <https://github.com/orenlab/codeclone/issues>
- Documentation: <https://orenlab.github.io/codeclone/claude-desktop-bundle/>

## Product decisions

- **Canonical MCP first**: Claude talks to the same CodeClone MCP surface used
  elsewhere.
- **Local and explicit**: the bundle starts only a local launcher and keeps
  transport fixed to `stdio`.
- **Small wrapper, not a shadow runtime**: Node is used only to launch and
  supervise `codeclone-mcp`.
- **Setup honesty**: if the launcher is missing, the wrapper fails with a clear
  install hint instead of pretending analysis is available.

## Development

Useful local checks:

```bash
node --check server/index.js
node --check src/launcher.js
node --check scripts/build-mcpb.mjs
node --test test/*.test.js
node scripts/build-mcpb.mjs
```
