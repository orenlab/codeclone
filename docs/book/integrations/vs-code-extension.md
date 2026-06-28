<!-- doc-scope: VS Code Extension contract. class: contract max-lines: 150 -->

# VS Code Extension

Setup guide: [VS Code setup](../../guide/integrations/vscode/setup.md).

## Trust model

The extension uses a **limited Restricted Mode**:

- onboarding and setup help remain available in untrusted workspaces
- local analysis and the local MCP server stay disabled until workspace trust
  is granted

The extension is not intended for virtual workspaces.

That is intentional: CodeClone reads repository contents, local git state, and
the local MCP launcher.

!!! warning "Workspace trust still matters"
    The extension runs as a workspace extension and requires VS Code `1.120.0`
    or newer, local filesystem access, local git access for changed-files review,
    and a local `codeclone-mcp` launcher or an explicitly configured one.
    CodeClone **`2.0.0` or newer** is required for core analysis, triage, and
    change-control MCP tools.

    **Engineering Memory** (Memory tree view, search, IDE governance approve/reject,
    trajectory dashboard) requires CodeClone **`2.1.0a1` or newer** with
    `query_engineering_memory` and governance tools on the resolved launcher.
    Older servers that pass the `2.0.0` gate still load the extension but show
    Memory features as unavailable until upgraded.

    In `auto` mode, launcher resolution prefers the current workspace virtualenv
    before `PATH`. Launcher override settings (`codeclone.mcp.command`,
    `codeclone.mcp.args`) are machine-scoped. Analysis-depth settings are
    resource-scoped so they can vary by workspace or folder.

## Settings

Authoritative definitions: `extensions/vscode-codeclone/package.json` →
`contributes.configuration.properties`.

### Launcher (machine-scoped)

| Setting                 | Default | Notes                                                                                                                                           |
|-------------------------|---------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| `codeclone.mcp.command` | `auto`  | Workspace venv, then `PATH`. User/remote settings.                                                                                              |
| `codeclone.mcp.args`    | `[]`    | Extra launcher argv. The extension injects `--ide-governance-channel` for Memory governance and session/audit tools (do not duplicate in args). |

### Analysis (resource-scoped)

| Setting                                    | Default    | Notes                                              |
|--------------------------------------------|------------|----------------------------------------------------|
| `codeclone.analysis.profile`               | `defaults` | `defaults`, `deeperReview`, or `custom`.           |
| `codeclone.analysis.cachePolicy`           | `reuse`    | `reuse` or `off`.                                  |
| `codeclone.analysis.changedDiffRef`        | `HEAD`     | Git ref for **Review Changes**.                    |
| `codeclone.analysis.coverageXml`           | `""`       | Explicit Cobertura path for Coverage Join.         |
| `codeclone.analysis.autoDetectCoverageXml` | `true`     | Use workspace-root `coverage.xml` when path empty. |
| `codeclone.analysis.minLoc`                | `10`       | Custom thresholds — only when `profile=custom`.    |
| `codeclone.analysis.minStmt`               | `6`        | Same.                                              |
| `codeclone.analysis.blockMinLoc`           | `20`       | Same.                                              |
| `codeclone.analysis.blockMinStmt`          | `8`        | Same.                                              |
| `codeclone.analysis.segmentMinLoc`         | `20`       | Same.                                              |
| `codeclone.analysis.segmentMinStmt`        | `10`       | Same.                                              |

### UI (window-scoped)

| Setting                      | Default | Notes                            |
|------------------------------|---------|----------------------------------|
| `codeclone.ui.showStatusBar` | `true`  | Workspace-level status bar item. |

### Engineering Memory search (resource-scoped)

These map to MCP `query_engineering_memory` parameters from
`extensions/vscode-codeclone/src/memorySearch.js` (`readMemorySearchSettings`).

| Setting                                | Default   | MCP mapping                             | Notes                                                                                                                                                                                                                                                                                                                                                 |
|----------------------------------------|-----------|-----------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `codeclone.memory.searchSemantic`      | `true`    | `semantic` on `mode=search` only        | Extension **asks** for semantic blend by default. Server still needs `[tool.codeclone.memory.semantic] enabled`, a built sidecar, and a provider. Use `codeclone[semantic-local]` + `embedding_provider="fastembed"` for semantic-quality recall; otherwise FTS-only or diagnostic/degraded results report `semantic.used: false` / provider details. |
| `codeclone.memory.searchIncludeDrafts` | `false`   | `include_drafts` (search)               | Drafts are still included automatically on `for_path` per memory contract.                                                                                                                                                                                                                                                                            |
| `codeclone.memory.searchIncludeStale`  | `false`   | `include_stale` (search and `for_path`) |                                                                                                                                                                                                                                                                                                                                                       |
| `codeclone.memory.searchMaxResults`    | `20`      | `max_results` (clamped 5–50)            |                                                                                                                                                                                                                                                                                                                                                       |
| `codeclone.memory.searchDetailLevel`   | `compact` | `detail_level`: `compact` or `full`     | `mode=get` always returns full records. Not exposed in **Configure Memory Search** (settings UI only).                                                                                                                                                                                                                                                |

!!! important "Extension default differs from server default"
    `searchSemantic` defaults to **`true` in VS Code** so the IDE requests semantic
    blend when the user searches. CodeClone's **repository** default remains
    `memory.semantic.enabled = false` until you opt in in `pyproject.toml`, install
    the semantic extras, and rebuild the sidecar (MCP
    `rebuild_semantic_index` or CLI `memory semantic rebuild`).

    **Configure Memory Search** updates `searchSemantic`, `searchIncludeDrafts`,
    `searchIncludeStale`, and `searchMaxResults` at `ConfigurationTarget.WorkspaceFolder`.
    `searchDetailLevel` is settings-editor only. Search queries must be 2–200 characters
    without control characters (`sanitizeSearchQuery`).

## State boundaries

The extension keeps three state classes visibly separate:

**Repository truth** — comes from CodeClone analysis through MCP and canonical
report semantics.

**Current run** — bounded by the active MCP session and the current latest run
used by the extension for a workspace.

**Reviewed markers** — session-local workflow markers only. They are in-memory
only, do not update baseline state, do not rewrite findings, and do not change
canonical report truth.

## Design rules

- **Native VS Code first**: tree views, status bar, Quick Pick, CodeLens, and
  file decorations before any custom UI.
- **Conservative by default**: the extension starts with the `defaults`
  profile (repo defaults or `pyproject`-resolved thresholds) and treats
  `deeperReview` or `custom` as explicit exploratory follow-ups.
- **Source-first**: findings prefer `Reveal Source` over detail panels;
  canonical detail and HTML report bridge are opt-in.
- **Report-only separation**: Overloaded Modules stay visually distinct from
  findings, gates, and health. `Security Surfaces` stay visually distinct too
  and remain boundary inventory rather than vulnerability claims.
- **Safe HTML bridge**: `Open in HTML Report` verifies the local file exists
  and is not older than the current run.
- **Session-local state**: reviewed markers shape review UX but never leak
  into repository truth.
- **Trajectory evidence**: dashboard/detail commands render MCP trajectory
  status, anomalies, exact agent-label aggregates, quality passports, and
  Patch Trail evidence without inventing IDE-local scoring.
- **First-run clarity**: onboarding leads to `Analyze Workspace`, not
  transport setup.
- **Restricted Mode honesty**: explain requirements without pretending
  analysis is available before trust is granted.

## Non-guarantees

- Exact view grouping and copy may evolve between extension releases.
- Internal client-side caching and view-model shaping may evolve as long as the
  extension remains faithful to MCP and canonical report semantics.
- Explorer decoration styling, review-loop polish, and other non-contract UI
  details may evolve without changing the extension contract.

## Source of truth

The extension reads the same canonical analysis semantics already exposed by
CodeClone CLI, canonical report JSON, and CodeClone MCP.

- CLI remains the scripting and CI surface.
- HTML remains the richest human report surface.
- MCP remains the read-only integration contract for agents and IDE clients.
- The VS Code extension is a guided IDE view over that MCP surface.

For the underlying interface contract, see
[MCP usage guide](../../guide/mcp/README.md) and
[MCP interface contract](../25-mcp-interface/index.md).
Trajectory scoring is defined by
[Trajectory quality and passport](../13-engineering-memory/trajectory-quality-and-passport.md).
