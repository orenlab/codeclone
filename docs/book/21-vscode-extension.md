# 21. VS Code Extension

## Purpose

Document the current contract and behavior of the VS Code extension shipped in
`extensions/vscode-codeclone/`.

This chapter describes the extension as an interface layer over existing
CodeClone contracts. It does not define a second analysis truth model.

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
  restricted-mode guidance, and report-only God Module detail
- lightweight Explorer file decorations for review-relevant files
- editor-local CodeLens and title actions for the active review target

## Workflow model

The intended IDE path mirrors CodeClone MCP:

1. `Analyze Workspace` or `Review Changes`
2. compact overview and priority review
3. review new regressions or production hotspots
4. reveal source
5. open canonical finding or remediation only when needed

This is deliberately different from a lint-list model. The extension should
prefer guided review over broad enumeration.

## Current capabilities

The extension currently supports:

- full-workspace analysis
- changed-files analysis against a configured git diff reference
- compact overview of structural health, current run state, and baseline drift
- review queues for new regressions, production hotspots, changed-scope
  findings, and report-only `God Modules`
- source reveal, peek, canonical finding detail, remediation detail, and
  session-local reviewed markers
- bounded MCP help topics inside the IDE
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

The extension runs as a workspace extension and requires:

- local filesystem access
- local git access for changed-files review
- a local `codeclone-mcp` launcher, or an explicitly configured launcher

For this reason:

- Restricted Mode support is `limited`
- untrusted workspaces may show setup/onboarding/help surfaces only
- local analysis and local MCP startup remain disabled until trust is granted
- virtual workspaces are unsupported

## Design decisions

The extension follows these implementation rules:

- **Native VS Code first**: tree views, status bar, Quick Pick, CodeLens, and
  file decorations come before any richer custom UI.
- **Source-first review**: findings prefer `Reveal Source` over immediate
  detail panels.
- **Explicit deepening**: canonical finding detail, remediation, and HTML
  report bridges remain opt-in actions.
- **Report-only separation**: `God Modules` stay clearly outside findings,
  gates, and health dimensions.
- **Safe local HTML bridge**: `Open in HTML Report` must verify that a local
  `report.html` exists and is not obviously older than the current run.
- **Session-local workflow state**: reviewed markers may shape the review UX
  but must not leak into repository truth.

## UX rules

The extension should preserve these product rules:

- The cheapest useful path should be the most obvious path.
- First-run UX should lead to `Analyze Workspace`, not transport setup detail.
- Review actions should prefer opening source before opening deeper structured
  detail.
- Report-only layers such as `God Modules` must remain visually distinct from
  findings, gates, and health dimensions.
- The extension should minimize noise and avoid duplicating the HTML report in
  the sidebar.
- Restricted Mode should still explain what the extension needs, without
  pretending local analysis is available before trust is granted.
- Accessibility labels should stay meaningful on tree items and status
  surfaces.

## Relationship to other interfaces

- CLI remains the scripting and CI surface.
- HTML remains the richest human report surface.
- MCP remains the read-only integration contract for agents and IDE clients.
- The VS Code extension is a guided IDE view over that MCP surface.

## Non-guarantees

- Exact view grouping and copy may evolve between beta releases.
- Internal client-side caching and view-model shaping may evolve as long as the
  extension remains faithful to MCP and canonical report semantics.
- Explorer decoration styling, review-loop polish, and other non-contract UI
  details may evolve without changing the extension contract.
