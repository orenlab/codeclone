# VS Code setup

Contract: [VS Code extension](../../../book/integrations/vs-code-extension.md).

## What it is for

The extension helps you:

- analyze the current workspace
- review changed files against a git diff
- start with a conservative first pass and lower thresholds only when you need
  a more sensitive follow-up
- focus on new regressions and production hotspots first
- jump directly to source locations
- open canonical finding or remediation detail only when needed
- inspect current-run `Coverage Join` facts without inventing extension-local interpretations
- inspect report-only `Security Surfaces` as security-relevant boundary inventory
- inspect report-only Overloaded Module candidates without treating them like findings

It does not create a second truth model and it does not mutate the repository.

## Install requirements

Install from the VS Code Marketplace: **`orenlab.codeclone`** (publisher
**orenlab**), or sideload a `.vsix` built from `extensions/vscode-codeclone`.

The extension needs a local `codeclone-mcp` launcher and VS Code `1.120.0` or newer
(`engines.vscode` in `package.json`).

Minimum supported CodeClone version: **`2.0.0`** (core analysis and change control).

Engineering Memory features (Memory tree, search, governance, trajectory views)
require **`2.1.0a1` or newer** on the resolved `codeclone-mcp` launcher.

In `auto` mode, it checks the current workspace virtualenv before falling back
to `PATH`. Runtime and version-mismatch messages identify that resolved launcher source.

Recommended install:

```bash
uv tool install --prerelease allow "codeclone[mcp]"
```

If you want the launcher inside the current environment instead:

```bash
uv pip install --prerelease allow "codeclone[mcp]"
```

Verify the launcher:

```bash
codeclone-mcp --help
```

When you run the CLI inside an interactive VS Code terminal, CodeClone may also
show a one-time extension hint after the summary. It is suppressed in quiet,
CI, and non-interactive runs, and is remembered per CodeClone version next to
the resolved project cache path.

## Main views

### Overview

Compact health, current run state, baseline drift, and next-best review action.
When the current run includes external Cobertura join facts, Overview also
shows a factual `Coverage Join` section sourced from canonical MCP metrics.
When MCP exposes `security_surfaces`, Overview also shows a compact report-only
`Security Surfaces` section.

### Hotspots

Primary operational view for:

- new regressions
- production hotspots
- changed-files findings
- report-only Security Surfaces
- report-only Overloaded Module candidates

### Runs & Session

Session-local state:

- local server availability
- current run identity
- reviewed findings
- MCP help topics, including the optional `coverage` topic on newer
  CodeClone/MCP servers

### Memory

Engineering Memory inbox: draft records, stale list, status, refresh/sync
actions, and human approve/reject through the IDE governance channel
(`prepare_governance` / `commit_governance` with session HMAC attestation). The
extension launches MCP with `--ide-governance-channel` and registers a
`SecretStorage` governance key on connect.

## Review model

The extension stays source-first:

- `Review Priorities` and `Next Hotspot` / `Previous Hotspot` drive the review
  loop
- `Reveal Source` is the default action for findings
- editor-local actions appear only when the current file matches the active
  review target
- Explorer decorations stay lightweight and focus on new, production, or
  changed-scope relevance
- report-only Security Surfaces stay source-first: reveal source, open compact
  detail, or copy a review brief without promoting them to findings

`Open in HTML Report` exists as an explicit bridge to the richer human report,
not as the primary IDE workflow.

## Blast radius, session, and audit commands

The extension also exposes structural change-controller helpers over MCP:

- **Show Blast Radius** — `get_blast_radius` for a repo-relative file path
- **Copy Blast Radius Brief** — same payload formatted for review notes
- **Show Session Stats** / **Show Controller Audit Trail** — IDE-only MCP tools
  (`get_workspace_session_stats`, `get_controller_audit_trail`) registered only
  when the extension launches `codeclone-mcp` with `--ide-governance-channel`.
  Payloads match CLI `--session-stats` and `--audit` via
  `codeclone/controller_insights/`.
- **Clear Session** — `clear_session_runs` (in-memory runs, reviewed markers,
  and workspace intent registry state for the MCP process)

These commands require workspace trust and an active MCP connection.

## Engineering Memory in the IDE

- **Memory** view — draft inbox, approve/reject through the IDE governance
  channel (`prepare_governance` / `commit_governance`), sync from run.
- **Search Engineering Memory** — QuickPick (`mode=search`; FTS + optional
  semantic per `codeclone.memory.searchSemantic`, default **on** in the extension).
- **Memory for Active File** — `mode=for_path` for the active editor path.
- **Open Memory Search Panel** / **Refresh Memory Search** — results webview.
- **Configure Memory Search** — workspace wizard for semantic, drafts, stale, and
  result limit (see **Engineering Memory search** settings below).
- **Show Trajectory Dashboard** — projection health, quality/outcome aggregates,
  anomalies, and recent trajectories.
- **Show Trajectory Detail** — full passport with quality/complexity
  calculations, Patch Trail, contract gates, incidents, steps, and evidence.
- **Copy Trajectory Dashboard Brief** — Markdown summary for review notes.

Server-side semantic still requires `[tool.codeclone.memory.semantic] enabled`,
the semantic sidecar, and a successful rebuild (`manage_engineering_memory`
`action=rebuild_semantic_index` for MCP agents, or `codeclone memory semantic
rebuild` for CLI/CI). Install
`codeclone[semantic-local]` and set `embedding_provider = "fastembed"` for local
semantic-quality recall; `codeclone[semantic-lancedb]` alone can run only the
deterministic diagnostic provider. See
[Engineering Memory](../../../book/13-engineering-memory/index.md).
Trajectory semantics:
[Trajectory quality and passport](../../../book/13-engineering-memory/trajectory-quality-and-passport.md).

## Open Triage

**Open Triage** (`codeclone.openProductionTriage`) calls `get_production_triage` for
the current run before opening the markdown panel. Repeated opens reuse the cached
payload for 5 seconds when the run is unchanged and not marked stale; concurrent
opens share one in-flight request.

## First-run path

1. Open the `CodeClone` view container.
2. Run `Analyze Workspace`.
3. Use `Review Priorities` or `Review Changes`.
4. If the first pass looks clean but you want smaller repeated units, open
   `Set Analysis Depth`.
5. Reveal source before opening deeper detail.

If the launcher is missing, use `Open Setup Help` from the extension.
