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
  and report-only God Module detail

## Workflow model

The intended IDE path mirrors CodeClone MCP:

1. `Analyze Workspace` or `Review Changes`
2. compact overview and priority review
3. review new regressions or production hotspots
4. reveal source
5. open canonical finding or remediation only when needed

This is deliberately different from a lint-list model. The extension should
prefer guided review over broad enumeration.

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

- a trusted workspace
- local filesystem access
- local git access for changed-files review
- a local `codeclone-mcp` launcher, or an explicitly configured launcher

For this reason:

- untrusted workspaces are unsupported
- virtual workspaces are unsupported

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

## Relationship to other interfaces

- CLI remains the scripting and CI surface.
- HTML remains the richest human report surface.
- MCP remains the read-only integration contract for agents and IDE clients.
- The VS Code extension is a guided IDE view over that MCP surface.

## Non-guarantees

- Exact view grouping and copy may evolve between beta releases.
- Internal client-side caching and view-model shaping may evolve as long as the
  extension remains faithful to MCP and canonical report semantics.
