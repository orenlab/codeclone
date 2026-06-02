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
- read-only with respect to source files, baselines, analysis cache, and
  canonical report artifacts; full 31-tool MCP passthrough via the bundled
  stdio launcher (change-control and session tools included)
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
- six bundled skills:
    - `codeclone-production-triage` — fast production-focused first pass
    - `codeclone-hotspots` — quick health snapshot
    - `codeclone-blast-radius` — standalone structural impact inspection
    - `codeclone-review` — full structural review session
    - `codeclone-change-control` — intent-first change workflow
    - `codeclone-engineering-memory` — scope-aware memory retrieval and candidates
- one agent:
    - `codeclone-structural-reviewer` (`agents/structural-reviewer.md`) —
      deterministic code reviewer backed by MCP tools
- two rules:
    - `codeclone-workflow.mdc` — MCP discipline (always active)
    - `codeclone-python.mdc` — Python file context (glob-triggered)
- three hooks (Python scripts under `hooks/`; no MCP calls):
    - `preToolUse` (matcher `Write|StrReplace|ApplyPatch|Shell`, `failClosed`) —
      blocks repository writes and non–read-only shell when the workspace registry
      has no live **active** intent (reads `codeclone.workspace_intent` for file
      and SQLite backends)
    - `postToolUse` (matcher `Write|StrReplace|ApplyPatch`) — advisory
      `additional_context` after Python source writes
    - `stop` (`loop_limit: 1`) — advisory `followup_message` when workflow
      intents look unclosed in the session transcript

## Runtime model

The plugin surface is additive:

- `mcp.json` contributes a local stdio MCP server definition via
  `python3 ./scripts/launch_mcp.py` (workspace `.venv` → Poetry env → PATH);
  the launcher does not filter tools — agents receive the full 31-tool MCP surface
- the skills contribute workflow guidance and starter prompts
- the rules enforce MCP-first discipline and Python-aware context
- the hooks enforce change control at tool time (`preToolUse`) and provide
  advisory reminders (`postToolUse`, `stop`)
- the agent provides a structured review protocol backed by MCP tools
- Cursor remains free to use direct MCP configuration alongside or instead of
  the plugin

The plugin does not rewrite user config or install CodeClone automatically.

## Distribution

- **Monorepo source:** `plugins/cursor-codeclone/`
- **Marketplace:** not listed in `.agents/plugins/marketplace.json` (that file is
  Codex-only for local development)
- **Install path:** symlink skills/rules/MCP into `.cursor/` or register the
  plugin directory through Cursor local plugin discovery
- **Standalone releases:** ship a full copy of
  `plugins/codeclone/scripts/launch_mcp.py` inside
  `plugins/cursor-codeclone/scripts/`; the monorepo entrypoint delegates to the
  Codex plugin launcher to avoid duplicate logic during development

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

### Project vs plugin registration

Cursor’s **Hooks** settings page lists hooks from `.cursor/hooks.json` (project)
and `~/.cursor/hooks.json` (user) only. Hooks declared in the plugin manifest
(`hooks/hooks.json` via `plugin.json`) are not included in that count.

Ship or install a **project** `.cursor/hooks.json` that invokes the plugin
scripts (see `plugins/cursor-codeclone/scripts/install-project-hooks.py`). The
CodeClone monorepo commits `.cursor/hooks.json` invoking
`python …/hooks/run_hook.py` (cross-platform; no shell scripts).

Hooks follow these invariants:

- **Bounded** — hooks return quickly (5-second timeout)
- **Deterministic gate** — `preToolUse` is fail-closed and reads the configured
  CodeClone workspace intent registry through the public `codeclone.workspace_intent`
  API; it does not parse plugin-local marker files or assume a file backend
- **Advisory follow-up** — `postToolUse` returns `additional_context`; `stop` may
  return `followup_message` (not mandatory actions)
- **Cursor contract** — use `file_path` / `tool_input.path` from hook payloads;
  `afterFileEdit` does not accept `followup_message` in current Cursor docs
- **Deterministic** — hooks use simple pattern matching, not heuristic analysis
- **No file-tool tunnels** — without an authorized intent, direct writes inside
  the repository root are blocked, including `.git/**`; only read-only Git
  inspection shell commands are allowed

### `enforce_scope`

`preToolUse` gate breadth (default `python`):

| Mode     | Gated without active intent                                      |
|----------|------------------------------------------------------------------|
| `python` | `.py` / `.pyi` writes and matching shell                         |
| `repo`   | Any path under the workspace root, including `.git/**`           |

Set via `.cursor/codeclone-hooks.json` (`enforce_scope`) or
`CODECLONE_HOOKS_ENFORCE_SCOPE`. Installer:
`uv run python plugins/cursor-codeclone/scripts/install-project-hooks.py --enforce-scope repo`.
Details: [Cursor plugin guide](../cursor-plugin.md).

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
- **Hook safety**: `preToolUse` is fail-closed for repository writes and
  non–read-only shell; `postToolUse` and `stop` stay advisory and non-blocking.
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
