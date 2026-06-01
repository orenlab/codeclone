# Cursor Plugin

**Structural Change Controller for AI-assisted Python development** — native
Cursor plugin. Source lives in `plugins/cursor-codeclone/`; the plugin bundles
an MCP server definition, six skills, one agent, two rules, and three hooks.

## What ships in the plugin

| Component                              | Path       | Purpose                                                                  |
|----------------------------------------|------------|--------------------------------------------------------------------------|
| `.cursor-plugin/plugin.json`           | Manifest   | Plugin metadata and component declarations                               |
| `mcp.json`                             | MCP server | Local stdio `codeclone-mcp` server definition                            |
| `skills/codeclone-review/`             | Skill      | Conservative-first full structural review                                |
| `skills/codeclone-hotspots/`           | Skill      | Quick hotspot discovery and health snapshot                              |
| `skills/codeclone-change-control/`     | Skill      | Intent-first change workflow with blast radius and verification          |
| `skills/codeclone-engineering-memory/` | Skill      | Engineering memory retrieval and candidate recording around edits        |
| `skills/blast-radius/`                 | Skill      | Standalone blast radius inspection before edits                          |
| `skills/production-triage/`            | Skill      | Fast production-focused triage and next-action recommendation            |
| `agents/structural-reviewer.md`        | Agent      | Deterministic structural code reviewer backed by MCP tools               |
| `rules/codeclone-workflow.mdc`         | Rule       | MCP workflow discipline (always active)                                  |
| `rules/codeclone-python.mdc`           | Rule       | Python file context (auto-triggers on `**/*.py`)                         |
| `hooks/hooks.json`                     | Hooks      | `preToolUse` change-control gate, `postToolUse` reminder, `stop` cleanup |
| `assets/`                              | Branding   | Plugin logo and icon                                                     |

## Install

The plugin expects a local `codeclone-mcp` launcher. Install CodeClone with
the MCP extra:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --help
```

### Project-level setup

Symlink the plugin into the project `.cursor/` directory:

```bash
mkdir -p .cursor/skills .cursor/rules .cursor/agents

# Skills
for d in plugins/cursor-codeclone/skills/*/; do
    ln -sfn "$(pwd)/$d" ".cursor/skills/$(basename $d)"
done

# Rules
for f in plugins/cursor-codeclone/rules/*.mdc; do
    ln -sfn "$(pwd)/$f" ".cursor/rules/$(basename $f)"
done

# MCP server
ln -sfn "$(pwd)/plugins/cursor-codeclone/mcp.json" .cursor/mcp.json

# Agent
ln -sfn "$(pwd)/plugins/cursor-codeclone/agents/structural-reviewer.md" \
    .cursor/agents/structural-reviewer.md
```

Add `.cursor/` to `.gitignore` if it is not already there.

!!! note "Marketplace"
    The Cursor plugin is **not** listed in `.agents/plugins/marketplace.json`.
    That file is Codex-only for local monorepo development. Install from
    `plugins/cursor-codeclone/` via symlinks or Cursor local plugin discovery.

    The bundled `mcp.json` runs `python3 ./scripts/launch_mcp.py`, which resolves
    `.venv` → Poetry env → `PATH`. In the monorepo that entrypoint delegates to
    `plugins/codeclone/scripts/launch_mcp.py`; standalone plugin releases must ship
    the full launcher body.

### Personal (global) setup

```bash
ln -sfn /path/to/codeclone/plugins/cursor-codeclone \
    ~/.cursor/plugins/local/codeclone
```

## Skills

### codeclone-production-triage

Fast production-focused first pass: health score, finding counts, top hotspots,
baseline status, and recommended next action. Two MCP calls:
`analyze_repository` then `get_production_triage`.

### codeclone-hotspots

Quick quality snapshot: health check, top risks, single-metric queries. The
cheapest useful path for answering ad-hoc questions about repository quality.

### codeclone-blast-radius

Standalone blast radius inspection before editing files. Shows dependents,
clone cohort, risk signals, do-not-touch boundaries, and guardrails. Read-only
— does not declare intent or start a change workflow.

### codeclone-review

Full structural review: clone triage, changed-scope review, health-oriented
refactor planning. Starts conservative with default thresholds, supports
deeper follow-up with lowered thresholds and run comparison.

### codeclone-change-control

Intent-first change workflow for repository edits. Declares scope before
editing, maps blast radius, verifies the patch against the contract, generates
a review receipt, and validates cited review claims. This is the governance
skill — use it whenever the task requires changing files.

### codeclone-engineering-memory

Scope-aware engineering memory: ranked context before edits (`get_relevant_memory`
with absolute `root`), path/symbol/search queries, and candidate recording before
`finish_controlled_change`. Complements change control; does not replace intent
declaration or patch verification.

## Agent

### structural-reviewer

Deterministic structural code reviewer that uses CodeClone MCP tools to assess
clone risk, complexity hotspots, coupling, and blast radius. Reports findings
with file paths and evidence, not opinions. Does not modify files or declare
intent.

## Rules

- **codeclone-workflow.mdc** (always active) — MCP workflow discipline: use MCP
  tools only, pass absolute roots, prefer `get_production_triage` after
  analysis, do not fall back to CLI or local report files.
- **codeclone-python.mdc** (glob: `**/*.py`) — auto-triggers when Python files
  are in context: run analysis before structural changes, check blast radius,
  do not introduce regressions.

## Hooks

### Why Settings → Hooks can show “Configured Hooks (0)”

The Hooks panel counts **project** and **user** hook files only:

| Source          | Path                                 | Shown in Hooks UI                                                             |
|-----------------|--------------------------------------|-------------------------------------------------------------------------------|
| Project         | `.cursor/hooks.json`                 | yes                                                                           |
| User            | `~/.cursor/hooks.json`               | yes                                                                           |
| Plugin manifest | `hooks/hooks.json` in the plugin dir | **no** (may still run when the plugin is enabled; do not rely on the counter) |

For the CodeClone repository, commit `.cursor/hooks.json` (see
`plugins/cursor-codeclone/scripts/install-project-hooks.py`). For other
projects, run that script once per repo (`python`, not bash — Windows-safe).

### Hook events

- **preToolUse** (matcher `Write|StrReplace|ApplyPatch|Shell`,
  `failClosed: true`) — **blocks** Agent writes when the configured CodeClone
  workspace intent registry has no live active intent. The hook calls the public
  `codeclone.workspace_intent` read-only API, so file and SQLite registry
  backends behave the same. Scope is configured per project:
    - `python` (default): `.py` / `.pyi` only
    - `repo`: any path under the workspace root (including `.git/**`) — all are
      gated; none are exempt from the intent requirement
      Configure via `.cursor/codeclone-hooks.json` (`enforce_scope`) or
      `CODECLONE_HOOKS_ENFORCE_SCOPE`. Without an authorized intent, only read-only
      Git inspection shell commands are allowed; `git apply`, commits, and direct
      `.git/**` file writes are blocked. Install: `uv run python
  plugins/cursor-codeclone/scripts/install-project-hooks.py --enforce-scope
  repo`. There is no env bypass for this gate.
- **postToolUse** (matcher `Write|StrReplace|ApplyPatch`) — after Agent writes
  `.py` / `.pyi`, injects `additional_context` with the change-control reminder
  (`analyze_repository`, `finish_controlled_change`, `get_relevant_memory` with
  absolute `root`).
- **stop** (`loop_limit: 1`) — when the session transcript shows
  `start_controlled_change` without matching `finish` / `intent_cleared`, emits
  an optional `followup_message`.

## Runtime model

Additive — the plugin provides a local MCP definition, six skills, one agent,
two rules, and three hooks. New canonical MCP surfaces from the local
`codeclone-mcp` version flow through directly; the bundled launcher does not
filter tools (full 31-tool passthrough). The plugin does not install a
second server binary or mutate Cursor settings.

## Read-only contract

Repository truth stays read-only: MCP must not mutate source files, baselines,
analysis cache, or canonical report artifacts. Change-control and session tools
may write ephemeral coordination state through the configured workspace intent
registry (file backend default: `.cache/codeclone/intents/`; SQLite supported)
and optional audit records when enabled.

## Current limits

- If you already configured `codeclone-mcp` manually in Cursor MCP settings,
  keep only one setup path to avoid duplicate MCP surfaces.
- The bundled `mcp.json` expects `codeclone-mcp` on `PATH` or configured with
  an absolute path.
- Hooks are Python scripts (`hooks/pre_tool_use_change_control.py`,
  `hooks/post-tool-use-python-edit.py`, `hooks/session-cleanup-check.py`)
  bundled with the plugin; `preToolUse` reads workspace intent state through
  `codeclone.workspace_intent`, not plugin-local marker files or file-only
  globs. The hooks do not call MCP directly.

## Further reading

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [Structural Change Controller](book/24-structural-change-controller.md)
- [Cursor plugin contract](book/25-cursor-plugin.md)
