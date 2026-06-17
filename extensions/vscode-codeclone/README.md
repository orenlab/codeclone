# CodeClone for VS Code

[![License](https://img.shields.io/github/license/orenlab/codeclone?style=flat-square&color=6366f1)](LICENSE)
[![Requires CodeClone](https://img.shields.io/badge/requires-codeclone_%3E%3D2.0.0-6366f1?style=flat-square)](https://orenlab.github.io/codeclone/)

Native VS Code surface for [codeclone-mcp](https://orenlab.github.io/codeclone/guide/mcp/) —
**Structural Change Controller for AI-assisted Python development**. Brings
baseline-aware structural analysis into the editor — triage-first, repository
read-only, and driven by the same canonical report as the CLI and HTML output. Session tools (`mark_finding_reviewed`, `clear_session_runs`) update
ephemeral MCP state only; they never mutate source, baselines, cache, or report
artifacts.

> **Not a linter panel.** CodeClone for VS Code is designed for structural review and
> refactoring flow, not diagnostics or Problems integration.

---

## Features

- **Hotspots view** — new regressions, production hotspots, and changed-files findings
  at a glance; report-only Security Surfaces and Overloaded Modules kept visually separate
- **Baseline-aware** — distinguishes known debt from new regressions against the stored baseline
- **Changed-files review** — `Review Changes` scopes analysis to the current diff via a configurable git ref
- **Blast Radius** — `Show Blast Radius` renders a concentric SVG diagram of structural
  impact for the active file; `Copy Blast Radius Brief` puts a Markdown summary on the clipboard
- **Session & audit insights** — `Show Session Stats` and `Show Controller Audit Trail` mirror
  CLI `--session-stats` and `--audit` in read-only webviews (IDE-only MCP tools, not exposed to agents)
- **Trajectory passports** — dashboard and detail views expose quality,
  complexity, anomalies, Patch Trail evidence, and agent aggregates
- **Coverage Join** — integrates `coverage.xml` to surface untested hotspots when available
- **Source-first navigation** — `Reveal Source` opens the exact location; `Next / Previous Hotspot`
  steps through active targets in the editor
- **Lightweight decorations** — Explorer file decorations and CodeLens appear only where relevant;
  no sidebar duplication of the HTML report
- **`Open in HTML Report`** — explicit bridge to the full report when a fresh local `report.html` exists

---

## Requirements

- VS Code `1.120.0+` (`engines.vscode` in `package.json`)
- Python workspace (trusted)
- `codeclone-mcp` launcher (`codeclone >= 2.0.0`)
- The **Memory** view (Engineering Memory) requires `codeclone >= 2.1.0a1`;
  on older servers it stays inactive and reports the required version.

---

## Install

Install the `codeclone-mcp` launcher before enabling the extension.

**Recommended (global tool via uv):**

```bash
uv tool install "codeclone[mcp]"
```

**Current environment only:**

```bash
uv pip install "codeclone[mcp]"
```

**Verify:**

```bash
codeclone-mcp --help
```

In `auto` mode the extension checks the current workspace virtualenv first,
then falls back to `PATH`. Version-mismatch messages identify the resolved launcher source.

---

## Getting started

1. Open a trusted Python workspace.
2. Open the **CodeClone** view container.
3. Run **Analyze Workspace**.
4. Start with **Review Priorities** or **Review Changes** as the first pass.
5. To tune sensitivity, open **Set Analysis Depth**.

If the launcher is missing, use **Open Setup Help** from the view or the command palette.

---

## Main views

### Overview

Compact repository health, current run state, baseline drift, and the next recommended
review action.

### Hotspots

The primary operational view. Surfaces:

- new regressions and production hotspots
- changed-files findings against the configured diff ref
- Coverage Join items when `coverage.xml` is available
- report-only Security Surfaces (boundary inventory, not vulnerability claims)
- report-only Overloaded Module candidates

Focus mode is explicit and persisted per workspace; `Recommended` is the default.

### Runs & Session

Bounded MCP session state: server availability, current run identity, reviewed findings,
and help topics. Reviewed markers are session-local and do not mutate the repository or report.

### Blast Radius

Visual structural impact analysis for the active file.

- **Show Blast Radius** — opens a WebviewPanel with a concentric SVG diagram
  showing origin, direct dependents, transitive dependents, and clone cohort.
  Risk signals (complexity, coverage, overloaded modules) are overlaid as
  colored dots. Do-not-touch boundaries and guardrails are listed below the
  diagram.
- **Copy Blast Radius Brief** — copies a structured Markdown summary of the
  same data to the clipboard for use in PR descriptions or review notes.

Both commands are available from the editor title context menu and the command
palette when a run is active and the workspace is trusted. The webview uses
`enableScripts: false` and a nonce-scoped Content Security Policy with no
external resource access.

### Session stats & controller audit

Workspace coordination dashboards (no analysis run required beyond MCP connection):

- **Show Session Stats** — live agents, change intents, lease health, latest cached
  run summary, and audit token footprint (`get_workspace_session_stats`)
- **Show Controller Audit Trail** — recent controller events when `audit_enabled=true`
  (`get_controller_audit_trail`)
- **Copy Session Stats Brief** / **Copy Controller Audit Brief** — Markdown summaries
  for review notes

Available from the **Session** view title bar when the workspace is trusted and connected.
These MCP tools register only when the extension launches the server with
`--ide-governance-channel`; agent clients on the default `codeclone-mcp` launcher do not
see them in `list_tools`.

### Memory (inbox + search)

The **Memory** view remains the governance inbox (draft approve/reject). Search
is separate so the tree stays focused on human review work:

- **Search Engineering Memory** — keyword QuickPick (`query_engineering_memory`
  mode=search; optional semantic re-rank via settings)
- **Memory for Active File** — records bound to the current editor path
  (mode=for_path)
- **Open Memory Search Panel** — read-only results webview (CSP, no scripts,
  allowlisted `command:` links to open a record)
- **Show Trajectory Dashboard** — status, agent/outcome aggregates, anomalies,
  and recent trajectories
- **Show Trajectory Detail** — quality passport, complexity factors, Patch
  Trail, contract gates, incidents, steps, and evidence
- **Copy Trajectory Dashboard Brief** — Markdown summary for review notes

Use **Configure Memory Search** to adjust semantic recall, drafts/stale filters,
and result limits per workspace.

Trajectory views are read-only projections from
`query_engineering_memory`; they do not create IDE-local workflow truth.

---

## Settings

Defaults and scopes match `package.json` → `contributes.configuration.properties`.

### Launcher

| Setting | Default | Scope | Description |
|---------|---------|-------|-------------|
| `codeclone.mcp.command` | `auto` | Machine | Launcher for `codeclone-mcp` (`auto`: workspace venv, then `PATH`). |
| `codeclone.mcp.args` | `[]` | Machine | Extra launcher argv. The extension injects `--ide-governance-channel` for Memory governance and session/audit MCP tools. |

### Analysis

| Setting | Default | Scope | Description |
|---------|---------|-------|-------------|
| `codeclone.analysis.profile` | `defaults` | Resource | `defaults`, `deeperReview`, or `custom`. |
| `codeclone.analysis.cachePolicy` | `reuse` | Resource | `reuse` or `off` for analysis requests. |
| `codeclone.analysis.changedDiffRef` | `HEAD` | Resource | Git ref for **Review Changes**. |
| `codeclone.analysis.coverageXml` | `""` | Resource | Cobertura path for Coverage Join. |
| `codeclone.analysis.autoDetectCoverageXml` | `true` | Resource | Use workspace-root `coverage.xml` when path is empty. |
| `codeclone.analysis.minLoc` | `10` | Resource | Custom clone thresholds (only when `profile=custom`). |
| `codeclone.analysis.minStmt` | `6` | Resource | Same. |
| `codeclone.analysis.blockMinLoc` | `20` | Resource | Same. |
| `codeclone.analysis.blockMinStmt` | `8` | Resource | Same. |
| `codeclone.analysis.segmentMinLoc` | `20` | Resource | Same. |
| `codeclone.analysis.segmentMinStmt` | `10` | Resource | Same. |

### UI

| Setting | Default | Scope | Description |
|---------|---------|-------|-------------|
| `codeclone.ui.showStatusBar` | `true` | Window | Workspace-level status bar item. |

### Engineering Memory search

| Setting | Default | Scope | Description |
|---------|---------|-------|-------------|
| `codeclone.memory.searchSemantic` | `true` | Resource | Pass `semantic=true` to MCP keyword search. FTS still runs when the server index is missing; server needs `memory.semantic` enabled + `semantic-lancedb` + rebuild for real blend. |
| `codeclone.memory.searchIncludeDrafts` | `false` | Resource | Include draft records in search / search panel (`include_drafts`). |
| `codeclone.memory.searchIncludeStale` | `false` | Resource | Include stale records (`include_stale`; also used for **Memory for Active File**). |
| `codeclone.memory.searchMaxResults` | `20` | Resource | Cap per search (5–50). |
| `codeclone.memory.searchDetailLevel` | `compact` | Resource | `compact` or `full` statement payloads in list modes. |

**Configure Memory Search** sets semantic, drafts, stale, and max results per workspace folder. **Detail level** is editor-settings only.

---

## Limitations

- No background analysis on save; no VS Code Problems / diagnostics integration.
- Reviewed markers are session-local only.
- `Open in HTML Report` requires a local `report.html` that is fresh for the current run.
- Virtual workspaces are not supported.

---

## Trust model

The extension accesses local filesystem and git state to run structural analysis.
Untrusted workspaces are supported in a limited setup/onboarding mode only;
full analysis and MCP are disabled until workspace trust is granted.

---

## Design decisions

- **No second truth model** — health, findings, and drift come exclusively from
  `codeclone-mcp` and canonical report semantics.
- **Repository read-only** — the extension never edits source files, baselines,
  caches, or report artifacts. **Mark Reviewed** and **Clear Session** call
  ephemeral MCP session tools only.
- **Curated MCP surface** — IDE commands invoke a fixed subset of MCP tools
  (analysis, triage, blast radius, review markers, session clear). Change-control
  tools remain on the server for agent clients but are not wired to VS Code UI
  commands.
- **Report-only separation** — Security Surfaces and Overloaded Modules are visible but
  intentionally excluded from findings, gates, and health scoring.
- **Source-first** — the default review action moves you to code before opening deeper detail.

---

## Documentation

- [CodeClone documentation](https://orenlab.github.io/codeclone/)
- [MCP usage guide](https://orenlab.github.io/codeclone/guide/mcp/)
- [MCP interface contract](https://orenlab.github.io/codeclone/book/25-mcp-interface/)

---

## Development

Open this folder in VS Code and press `F5` to launch an Extension Development Host.

```bash
node --check src/support.js
node --check src/mcpClient.js
node --check src/extension.js
node --test test/*.test.js
node test/runExtensionHost.js
```
