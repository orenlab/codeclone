# VS Code Extension

CodeClone ships a stable VS Code extension in `extensions/vscode-codeclone/`.

It is a native IDE surface over `codeclone-mcp` and is designed for
baseline-aware, triage-first structural review inside the editor.

Marketplace: [CodeClone for VS Code](https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone)

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

The extension needs a local `codeclone-mcp` launcher and VS Code `1.100.0` or newer
(`engines.vscode` in `package.json`).

Minimum supported CodeClone version: `2.0.0`.

In `auto` mode, it checks the current workspace virtualenv before falling back
to `PATH`. Runtime and version-mismatch messages identify that resolved launcher source.

Recommended install:

```bash
uv tool install "codeclone[mcp]"
```

If you want the launcher inside the current environment instead:

```bash
uv pip install "codeclone[mcp]"
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

Server-side semantic still requires `[tool.codeclone.memory.semantic] enabled`,
the semantic sidecar, and a successful rebuild (`manage_engineering_memory`
`action=rebuild_semantic_index` for MCP agents, or `codeclone memory semantic
rebuild` for CLI/CI). Install
`codeclone[semantic-local]` and set `embedding_provider = "fastembed"` for local
semantic-quality recall; `codeclone[semantic-lancedb]` alone can run only the
deterministic diagnostic provider. See
[Engineering Memory](book/26-engineering-memory.md).

Full contract: [VS Code extension (book)](book/21-vscode-extension.md),
[Engineering Memory](book/26-engineering-memory.md).

## Open Production Triage

**Open Production Triage** calls `get_production_triage` for the current run before
opening the markdown panel. Repeated opens reuse the cached payload for 5 seconds
when the run is unchanged and not marked stale; concurrent opens share one
in-flight request.

## First-run path

1. Open the `CodeClone` view container.
2. Run `Analyze Workspace`.
3. Use `Review Priorities` or `Review Changes`.
4. If the first pass looks clean but you want smaller repeated units, open
   `Set Analysis Depth`.
5. Reveal source before opening deeper detail.

If the launcher is missing, use `Open Setup Help` from the extension.

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

## Settings

Authoritative definitions: `extensions/vscode-codeclone/package.json` →
`contributes.configuration.properties`.

### Launcher (machine-scoped)

| Setting | Default | Notes |
|---------|---------|-------|
| `codeclone.mcp.command` | `auto` | Workspace venv, then `PATH`. User/remote settings. |
| `codeclone.mcp.args` | `[]` | Extra launcher argv. The extension injects `--ide-governance-channel` for Memory governance and session/audit tools (do not duplicate in args). |

### Analysis (resource-scoped)

| Setting | Default | Notes |
|---------|---------|-------|
| `codeclone.analysis.profile` | `defaults` | `defaults`, `deeperReview`, or `custom`. |
| `codeclone.analysis.cachePolicy` | `reuse` | `reuse` or `off`. |
| `codeclone.analysis.changedDiffRef` | `HEAD` | Git ref for **Review Changes**. |
| `codeclone.analysis.coverageXml` | `""` | Explicit Cobertura path for Coverage Join. |
| `codeclone.analysis.autoDetectCoverageXml` | `true` | Use workspace-root `coverage.xml` when path empty. |
| `codeclone.analysis.minLoc` | `10` | Custom thresholds — only when `profile=custom`. |
| `codeclone.analysis.minStmt` | `6` | Same. |
| `codeclone.analysis.blockMinLoc` | `20` | Same. |
| `codeclone.analysis.blockMinStmt` | `8` | Same. |
| `codeclone.analysis.segmentMinLoc` | `20` | Same. |
| `codeclone.analysis.segmentMinStmt` | `10` | Same. |

### UI (window-scoped)

| Setting | Default | Notes |
|---------|---------|-------|
| `codeclone.ui.showStatusBar` | `true` | Workspace-level status bar item. |

### Engineering Memory search (resource-scoped)

These map to MCP `query_engineering_memory` parameters from
`extensions/vscode-codeclone/src/memorySearch.js` (`readMemorySearchSettings`).

| Setting | Default | MCP mapping | Notes |
|---------|---------|-------------|-------|
| `codeclone.memory.searchSemantic` | `true` | `semantic` on `mode=search` only | Extension **asks** for semantic blend by default. Server still needs `[tool.codeclone.memory.semantic] enabled`, a built sidecar, and a provider. Use `codeclone[semantic-local]` + `embedding_provider="fastembed"` for semantic-quality recall; otherwise FTS-only or diagnostic/degraded results report `semantic.used: false` / provider details. |
| `codeclone.memory.searchIncludeDrafts` | `false` | `include_drafts` (search) | Drafts are still included automatically on `for_path` per memory contract. |
| `codeclone.memory.searchIncludeStale` | `false` | `include_stale` (search and `for_path`) | |
| `codeclone.memory.searchMaxResults` | `20` | `max_results` (clamped 5–50) | |
| `codeclone.memory.searchDetailLevel` | `compact` | `detail_level`: `compact` or `full` | `mode=get` always returns full records. Not exposed in **Configure Memory Search** (settings UI only). |

**Configure Memory Search** writes `searchSemantic`, `searchIncludeDrafts`,
`searchIncludeStale`, and `searchMaxResults` to the workspace folder target.
Query length: 2–200 characters (`sanitizeSearchQuery` in `memorySearch.js`).

## Source of truth

The extension reads the same canonical analysis semantics already exposed by:

- CodeClone CLI
- canonical report JSON
- CodeClone MCP

For the underlying interface contract, see:

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [VS Code extension contract](book/21-vscode-extension.md)
