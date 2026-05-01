# 21. VS Code Extension

## Purpose

Document the current contract and behavior of the VS Code extension shipped in
`extensions/vscode-codeclone/`.

This chapter describes the extension as an interface layer over existing
CodeClone contracts. It does not define a second analysis truth model.

Marketplace: [orenlab.codeclone](https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone)

!!! note "No second truth path"
    The extension is a guided IDE client over `codeclone-mcp`. It may reshape
    review UX, but it must not recompute findings, health, or report truth
    independently from MCP and canonical report semantics.

## Position in the platform

The VS Code extension is:

- a native IDE client over `codeclone-mcp`
- read-only with respect to repository state
- baseline-aware and triage-first
- code-centered rather than report-dashboard-centered
- limited in Restricted Mode and fully active only after workspace trust

The extension exists to make the current CodeClone review workflow easier to
use inside the editor. It must not reinterpret report semantics or invent
findings outside canonical report and MCP payloads.

## Source of truth

The extension reads from:

- MCP tool responses
- MCP session-local reviewed state
- canonical report semantics already exposed through MCP

It must not:

- run a second analysis engine in the extension layer
- recompute health or finding semantics independently
- mutate source files, baselines, cache, or report artifacts

## Current surface

The extension currently exposes three native VS Code views:

- `Overview`
- `Hotspots`
- `Runs & Session`

It also provides:

- one workspace-level status bar item
- command palette entry points for analysis and review
- one onboarding walkthrough
- markdown detail panels for findings, remediation, help topics, setup help,
  restricted-mode guidance, and report-only detail for `Security Surfaces` and
  `Overloaded Modules`
- lightweight Explorer file decorations for review-relevant files
- editor-local CodeLens and title actions for the active review target

## Workflow model

The intended IDE path mirrors CodeClone MCP:

1. `Analyze Workspace` or `Review Changes`
2. compact overview and priority review
3. review new regressions or production hotspots
4. use `Set Analysis Depth` only when you need a higher-sensitivity follow-up
5. reveal source
6. open canonical finding or remediation only when needed

This is deliberately different from a lint-list model. The extension should
prefer guided review over broad enumeration.

## Current capabilities

The extension currently supports:

- full-workspace analysis
- changed-files analysis against a configured git diff reference
- conservative default analysis with an explicit deeper-review or custom-threshold
  follow-up profile
- compact overview of structural health, current run state, baseline drift, and
  current-run `Coverage Join` facts when MCP exposes `metrics.coverage_join`,
  plus report-only `Security Surfaces` when MCP exposes
  `metrics.security_surfaces`
- review queues for new regressions, production hotspots, changed-scope
  findings, and report-only `Security Surfaces` / `Overloaded Modules`
- source reveal, peek, canonical finding detail, remediation detail, and
  session-local reviewed markers
- bounded MCP help topics inside the IDE, with the optional `coverage` topic on
  newer CodeClone/MCP servers
- explicit HTML-report bridge when a local HTML report already exists

These capabilities must remain clients of MCP and canonical report truth rather
than parallel extension-only logic.

## State boundaries

The extension must keep three state classes visibly separate:

### Repository truth

Comes from CodeClone analysis through MCP and canonical report semantics.

### Current run

Bounded by the active MCP session and the current latest run used by the
extension for a workspace.

### Reviewed markers

Session-local workflow markers only.

Reviewed markers:

- are in-memory only
- do not update baseline state
- do not rewrite findings
- do not change canonical report truth

## Trust and runtime model

!!! warning "Workspace trust still matters"
    The extension is intentionally limited in Restricted Mode. Local analysis,
    local git access, and local MCP startup remain disabled until the workspace
    is trusted.

The extension runs as a workspace extension and requires:

- local filesystem access
- local git access for changed-files review
- a local `codeclone-mcp` launcher, or an explicitly configured launcher
- CodeClone `2.0.0` or newer

In `auto` mode, launcher resolution prefers the current workspace virtualenv
before `PATH`. Runtime and version-mismatch messages identify that resolved launcher source.

Launcher override settings (`codeclone.mcp.command`, `codeclone.mcp.args`) are
machine-scoped. Analysis-depth settings are resource-scoped so they can vary by
workspace or folder.

For this reason:

- Restricted Mode support is `limited`
- untrusted workspaces may show setup/onboarding/help surfaces only
- local analysis and local MCP startup remain disabled until trust is granted
- virtual workspaces are unsupported

## Design rules

- **Native VS Code first**: tree views, status bar, Quick Pick, CodeLens, and
  file decorations before any custom UI.
- **Conservative by default**: the extension starts with repo defaults or
  `pyproject`-resolved thresholds and treats lower-threshold analysis as an
  explicit exploratory follow-up.
- **Source-first**: findings prefer `Reveal Source` over detail panels;
  canonical detail and HTML report bridge are opt-in.
- **Report-only separation**: Overloaded Modules stay visually distinct from
  findings, gates, and health. `Security Surfaces` stay visually distinct too
  and remain boundary inventory rather than vulnerability claims.
- **Safe HTML bridge**: `Open in HTML Report` verifies the local file exists
  and is not older than the current run.
- **Session-local state**: reviewed markers shape review UX but never leak
  into repository truth.
- **First-run clarity**: onboarding leads to `Analyze Workspace`, not
  transport setup.
- **Restricted Mode honesty**: explain requirements without pretending
  analysis is available before trust is granted.

## Relationship to other interfaces

- CLI remains the scripting and CI surface.
- HTML remains the richest human report surface.
- MCP remains the read-only integration contract for agents and IDE clients.
- The VS Code extension is a guided IDE view over that MCP surface.

## Non-guarantees

- Exact view grouping and copy may evolve between extension releases.
- Internal client-side caching and view-model shaping may evolve as long as the
  extension remains faithful to MCP and canonical report semantics.
- Explorer decoration styling, review-loop polish, and other non-contract UI
  details may evolve without changing the extension contract.
