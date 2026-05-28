# 25. Cursor Plugin

## Purpose

Document the current contract and behavior of the Cursor plugin sourced from
`plugins/cursor-codeclone/`.

This chapter describes the plugin as a Cursor discovery and AI guidance layer
over existing CodeClone MCP contracts.

!!! note "Guidance layer only"
    The plugin contributes discovery metadata, a local MCP definition, skills,
    rules, hooks, and an agent definition. It does not add a second analyzer or
    Cursor-only finding semantics.

## Position in the platform

The Cursor plugin is:

- sourced from `plugins/cursor-codeclone/` in this monorepo
- backed by the Cursor Plugin manifest at `.cursor-plugin/plugin.json`
- read-only with respect to repository state
- a composition of local MCP server metadata, AI skills, rules, hooks, and an
  agent definition
- a native Cursor setup surface, not a second extension model

## Source of truth

The plugin delegates analysis to the existing `codeclone-mcp` launcher and
guides AI agent usage through bundled skills and rules.

New canonical MCP surfaces flow through from the resolved local server version.
That includes current-run metric families such as `Coverage Join` and the
optional `coverage` help topic when that server supports them.

It must not:

- run a second analysis engine
- redefine findings, health, or gates
- mutate source files, baselines, cache, or report artifacts
- drift away from canonical MCP semantics

## Current surface

The plugin currently provides:

- `.cursor-plugin/plugin.json` — plugin manifest
- `mcp.json` — local stdio MCP server definition
- five bundled skills:
    - `codeclone-production-triage` — fast production-focused first pass
    - `codeclone-hotspots` — quick health snapshot
    - `codeclone-blast-radius` — standalone structural impact inspection
    - `codeclone-review` — full structural review session
    - `codeclone-change-control` — intent-first change workflow
- one agent:
    - `structural-reviewer` — deterministic code reviewer backed by MCP tools
- two rules:
    - `codeclone-workflow.mdc` — MCP discipline (always active)
    - `codeclone-python.mdc` — Python file context (glob-triggered)
- two hooks:
    - `afterFileEdit` — post-edit re-analysis reminder
    - `stop` — session-end intent cleanup check

## Runtime model

The plugin surface is additive:

- `mcp.json` contributes a local stdio MCP server definition
- the skills contribute workflow guidance and starter prompts
- the rules enforce MCP-first discipline and Python-aware context
- the hooks provide automated reminders for re-analysis and intent hygiene
- the agent provides a structured review protocol backed by MCP tools
- Cursor remains free to use direct MCP configuration alongside or instead of
  the plugin

The plugin does not rewrite user config or install CodeClone automatically.

## Skill contract

Each skill follows these invariants:

- **MCP tools only** — no fallback to CLI or local report files
- **Absolute roots** — analysis tools receive absolute repository paths
- **Source of truth** — CodeClone findings are reported as-is, not reinterpreted
- **Conservative first pass** — default thresholds unless the user explicitly
  asks for a deeper review
- **Scope discipline** — change control skills enforce declare/check/verify/clear

Skills are invocable via `/skill-name` in Cursor chat. Each skill's `SKILL.md`
contains the full workflow, rules, and non-goals.

## Hook contract

Hooks follow these invariants:

- **Non-blocking** — hooks return quickly (5-second timeout) and do not block
  agent execution
- **Advisory only** — hooks return `followup_message` suggestions, not
  mandatory actions
- **Deterministic** — hooks use simple pattern matching, not heuristic analysis
- **Fail-open** — hook failures do not prevent the agent from continuing

## Agent contract

The structural reviewer agent:

- uses CodeClone MCP tools exclusively for evidence
- does not modify files or declare change intent
- does not suppress or dismiss findings
- does not treat report-only signals as CI failures or vulnerability claims
- reports with file paths, finding IDs, and severities from CodeClone

## Design rules

- **Cursor-native packaging**: keep source under `plugins/cursor-codeclone/`
  and use `.cursor-plugin/plugin.json` as the manifest.
- **Canonical MCP first**: all analysis flows through `codeclone-mcp`.
- **Skill guidance, not analysis logic**: skills teach CodeClone workflows but
  do not create new findings.
- **Rule discipline**: rules enforce MCP-first usage and prevent fallback to
  CLI or manual reinterpretation.
- **Hook safety**: hooks are advisory, non-blocking, and fail-open.
- **Agent honesty**: the structural reviewer reports deterministic evidence, not
  opinions.
- **No hidden installation side effects**: the plugin does not patch Cursor
  settings or install binaries.
- **Launcher honesty**: the plugin assumes `codeclone-mcp` is already
  installable in the current workspace or reachable on `PATH`.

## Relationship to other interfaces

- CLI remains the scripting and CI surface.
- MCP remains the cross-client integration contract.
- VS Code extension remains the native IDE view surface.
- Codex plugin remains the Codex-native discovery surface.
- The Cursor plugin is the native Cursor AI discovery and governance layer for
  CodeClone.

## Non-guarantees

- Cursor plugin UI presentation and skill discovery may evolve independently
  of the plugin manifest content.
- Users who already configured `codeclone-mcp` manually may prefer the direct
  MCP path over the bundled plugin MCP definition.
- Hook behavior may be refined as Cursor's hook API evolves.
