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
- versioned in `.cursor-plugin/plugin.json` (currently **`0.1.0`**, separate
  from the CodeClone package release line)
- read-only with respect to source files, baselines, analysis cache, and
  canonical report artifacts; full **31-tool** MCP passthrough via
  `python3 ./scripts/launch_mcp.py` → `codeclone-mcp` (no
  `--ide-governance-channel`)
- a composition of local MCP server metadata, AI skills, rules, hooks, and an
  agent definition
- a native Cursor setup surface, not a second extension model

## Source of truth

The plugin delegates analysis to the existing `codeclone-mcp` launcher and
guides AI agent usage through bundled skills and rules.

New canonical MCP surfaces flow through from the resolved local server version
without plugin-side filtering. That includes Engineering Memory tools,
optional semantic search (server-configured), Coverage Join, and the optional
`coverage` help topic when supported.

It must not:

- run a second analysis engine
- redefine findings, health, or gates
- mutate source files, baselines, cache, or report artifacts
- drift away from canonical MCP semantics

## Current surface

### Manifest and MCP

| Artifact | Contract |
|----------|----------|
| `.cursor-plugin/plugin.json` | Declares `skills/`, `rules/`, `agents/`, `hooks`, `mcpServers` → `mcp.json` |
| `mcp.json` | `command: python3`, `args: ["./scripts/launch_mcp.py"]` |
| `scripts/launch_mcp.py` | Monorepo: delegates to `plugins/codeclone/scripts/launch_mcp.py` |

### Skills (six)

Invoke ids come from each `SKILL.md` `name:` field (folder names may differ):

| `name` | Typical MCP sequence |
|--------|----------------------|
| `codeclone-production-triage` | `analyze_repository` → `get_production_triage` |
| `codeclone-hotspots` | `analyze_repository` → focused checks |
| `codeclone-blast-radius` | `analyze_repository` → `get_blast_radius` (no intent) |
| `codeclone-review` | Full review (conservative first) |
| `codeclone-change-control` | `start_controlled_change` / `finish_controlled_change` workflow |
| `codeclone-engineering-memory` | `get_relevant_memory`, `query_engineering_memory`, drafts |

### Agent

- `codeclone-structural-reviewer` — `agents/structural-reviewer.md`; read-only
  evidence-backed review

### Rules (three)

| Rule | Activation |
|------|------------|
| `codeclone-workflow.mdc` | `alwaysApply` — MCP discipline |
| `change-control-gate.mdc` | `alwaysApply` — hard edit/finish gate when MCP connected |
| `codeclone-python.mdc` | `globs: **/*.py` — Python structural context |

### Hooks (three events)

Plugin manifest `hooks/hooks.json` routes through `hooks/run_hook.py`:

| Event | Matcher | Behavior |
|-------|---------|----------|
| `preToolUse` | `Write\|StrReplace\|ApplyPatch\|Shell` | Fail-closed intent gate via `codeclone.workspace_intent` |
| `postToolUse` | `Write\|StrReplace\|ApplyPatch` | `additional_context` after **Python** edits only |
| `stop` | `loop_limit: 1` | Advisory unclosed-intent `followup_message` |

Project install (`scripts/install-project-hooks.py`) writes `.cursor/hooks.json`
and `.cursor/codeclone-hooks.json` (`enforce_scope`: `python` or `repo`).

## Runtime model

The plugin surface is additive:

- `mcp.json` starts the shared launcher (workspace `.venv` → Poetry → `PATH`)
- skills and rules teach the documented MCP workflow
- hooks optionally enforce intent at tool time (see [Cursor plugin guide](../cursor-plugin.md))
- Cursor may also use a direct MCP config — avoid duplicate servers

The plugin does not rewrite user settings or install CodeClone automatically.

## Distribution

- **Monorepo source:** `plugins/cursor-codeclone/`
- **Marketplace:** not in `.agents/plugins/marketplace.json` (Codex-only entry)
- **Install:** Cursor local plugin discovery (recommended) or `.cursor/` symlinks
- **Standalone releases:** ship full `plugins/codeclone/scripts/launch_mcp.py` body

## Skill contract

Each skill follows these invariants:

- **MCP tools only** — no CLI or local report fallbacks
- **Absolute roots** — analysis and memory tools require absolute `root`
- **Source of truth** — report CodeClone findings as-is
- **Conservative first pass** unless the user requests deeper sensitivity
- **Workflow tools preferred** — `start_controlled_change` /
  `finish_controlled_change` for edits; atomic verify is advanced/fallback
- **Engineering Memory** — optional semantic search when server index is built;
  human approve via VS Code only ([Engineering Memory](26-engineering-memory.md))

Skills are invocable via `/name` in Cursor chat (see each `SKILL.md`).

## Hook contract

See [Cursor plugin guide — Hooks](../cursor-plugin.md#hooks). Hooks read
`codeclone.workspace_intent`; they do not invoke MCP.

`enforce_scope` (`python` vs `repo`) is configured in `.cursor/codeclone-hooks.json`
or `CODECLONE_HOOKS_ENFORCE_SCOPE`.

## Agent contract

The structural reviewer agent:

- uses CodeClone MCP tools exclusively for evidence
- does not modify files or declare change intent
- does not treat report-only signals as CI failures or vulnerability claims

## Design rules

- **Cursor-native packaging** under `plugins/cursor-codeclone/`
- **Canonical MCP first** — launcher resolves `codeclone-mcp`, no tool filtering
- **Rules + skills** — `change-control-gate` always on; skills carry workflows
- **Hook safety** — `preToolUse` fail-closed; `postToolUse` / `stop` advisory
- **No hidden installs** — plugin does not patch Cursor or install Python packages

## Relationship to other interfaces

- CLI — scripting and CI
- MCP — cross-client contract (31 agent tools here; 33 with VS Code IDE channel)
- VS Code extension — IDE views, Memory governance UI, session/audit webviews
- Codex plugin — four overlapping skills (no standalone production-triage /
  blast-radius skills)

## Non-guarantees

- Cursor UI for skills/hooks may evolve independently of manifest content
- Manual symlink installs may omit bundled rules/hooks unless the full plugin dir
  is registered
- Hook behavior follows Cursor's hook API contract
