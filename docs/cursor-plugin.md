<!-- doc-scope: SINGLE PAGE for Cursor plugin — usage AND contract merged.
     owns: plugin contents, install, skills (6), agent, rules (3), hooks (3),
       distribution, skill/hook/agent contracts, design rules, non-guarantees.
     does-not-own: MCP contract (→ book/25), engineering memory (→ book/13),
       change controller (→ book/12).
     rule: replaces former guide + book/25-cursor split. Do NOT re-split. -->
# Cursor Plugin

**Structural Change Controller for AI-assisted Python development** — native
Cursor plugin. Source lives in `plugins/cursor-codeclone/`; the plugin bundles
an MCP server definition, six skills, one agent, **three** rules, and three
hooks (hook **scripts** are not modified here — behavior described from current
code).

Plugin manifest version (`plugins/cursor-codeclone/.cursor-plugin/plugin.json`):
**`0.1.0`** (independent of the CodeClone Python package version in
`pyproject.toml`).

!!! note "Guidance layer only"
    The plugin contributes discovery metadata, a local MCP definition, skills,
    rules, hooks, and an agent definition. It does not add a second analyzer or
    Cursor-only finding semantics.

## What ships in the plugin

| Component | Path | Purpose |
|-----------|------|---------|
| `.cursor-plugin/plugin.json` | Manifest | `skills/`, `rules/`, `agents/`, `hooks/hooks.json`, `mcp.json` |
| `mcp.json` | MCP | `python3` + `./scripts/launch_mcp.py` — resolves `codeclone-mcp` (`.venv` → Poetry → `PATH`) |
| Skills (6) | `skills/*/` | See table below |
| Agent | `agents/structural-reviewer.md` | Invoke id: **`codeclone-structural-reviewer`** |
| Rules (3) | `rules/*.mdc` | See **Rules** |
| Hooks | `hooks/hooks.json` | Dispatches via `hooks/run_hook.py` (plugin manifest; optional project install) |
| `scripts/install-project-hooks.py` | Installer | Writes `.cursor/hooks.json` + `.cursor/codeclone-hooks.json` |
| `assets/` | Branding | Logo and icon |

### Skills (directory vs chat command)

Chat commands use the `name:` field in each `SKILL.md` (not always the folder
name on disk):

| Folder on disk | Chat command (`name`) | Primary MCP flow |
|----------------|----------------------|------------------|
| `production-triage/` | `/codeclone-production-triage` | `analyze_repository` → `get_production_triage` |
| `codeclone-hotspots/` | `/codeclone-hotspots` | `analyze_repository` → hotspots / `check_*` |
| `blast-radius/` | `/codeclone-blast-radius` | `analyze_repository` → `get_blast_radius` (read-only) |
| `codeclone-review/` | `/codeclone-review` | Full review loop (conservative first) |
| `codeclone-change-control/` | `/codeclone-change-control` | `start_controlled_change` → edit → `finish_controlled_change` |
| `codeclone-engineering-memory/` | `/codeclone-engineering-memory` | `get_relevant_memory`, `query_engineering_memory`, drafts |

Codex plugin ships the overlapping subset (review, hotspots, change-control,
engineering-memory) but **not** standalone production-triage or blast-radius
skills.

## Install

Install `codeclone[mcp]` so `launch_mcp.py` can resolve `codeclone-mcp`:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --help
```

### Recommended: Cursor plugin discovery

Register the plugin directory (loads manifest, skills, rules, hooks, and
`mcp.json` together):

```bash
ln -sfn /path/to/codeclone/plugins/cursor-codeclone ~/.cursor/plugins/local/codeclone
```

Reload Cursor. Enable the plugin for trusted workspaces.

### Optional: manual `.cursor/` symlinks

Only if you are not using plugin discovery — symlink skills, rules, agent, and
MCP separately (see monorepo comments in older guides). Prefer plugin discovery
so all three rules and hook manifest stay bundled.

### Project hooks (Hooks UI)

```bash
uv run python plugins/cursor-codeclone/scripts/install-project-hooks.py
# full-repo gate:
uv run python plugins/cursor-codeclone/scripts/install-project-hooks.py --enforce-scope repo
```

Writes:

- `.cursor/hooks.json` — shown in **Settings → Hooks**
- `.cursor/codeclone-hooks.json` — `enforce_scope` (`python` default, or `repo`)

Do **not** commit generated files (machine-local Python paths). This monorepo
ignores `/.cursor/` in `.gitignore`.

!!! note "Marketplace"
    Not listed in `.agents/plugins/marketplace.json` (Codex-only). Install from
    `plugins/cursor-codeclone/` via Cursor local plugin discovery or symlinks.

## Skills

### codeclone-production-triage

Two MCP calls: `analyze_repository` then `get_production_triage`. Baseline-relative
triage — not patch-local verify. Suggests `codeclone-review` for a deeper session.

### codeclone-hotspots

Cheapest ad-hoc snapshot after `analyze_repository`; prefer `list_hotspots` /
`check_*` before broad `list_findings`. Optional `help(topic="coverage")` when
Coverage Join semantics matter.

### codeclone-blast-radius

Read-only: `get_blast_radius` after analysis. Does **not** call
`start_controlled_change`. Use `codeclone-change-control` for edits.

### codeclone-review

Conservative-first full review; optional deeper pass with explicit user request.
Does not declare intent by itself.

### codeclone-change-control

Normal edit cycle uses workflow tools (not legacy-only atomic path):

`analyze_repository` → `start_controlled_change` → `get_relevant_memory` → edit
in scope → `analyze_repository` (when after-run required) → optional
`record_candidate` → `finish_controlled_change`.

Queue/recovery: `manage_change_intent` (`promote`, `recover`, …). Atomic
`check_patch_contract` / `create_review_receipt` are advanced/debug only when
workflow tools are unavailable.

### codeclone-engineering-memory

Scope memory before edits; optional `semantic=true` on `mode=search` when
`[tool.codeclone.memory.semantic]` is enabled, the semantic sidecar is installed,
and semantic index rebuild succeeded (`manage_engineering_memory`
`action=rebuild_semantic_index` or CLI `memory semantic rebuild`). Use
`codeclone[semantic-local]`
plus `embedding_provider = "fastembed"` for local semantic-quality recall;
`codeclone[semantic-lancedb]` alone supports only the deterministic diagnostic
provider. Human
approve/reject: VS Code **Memory** view only (MCP agents cannot approve).

Full contract: [Engineering Memory](book/13-engineering-memory.md).

## Agent

### codeclone-structural-reviewer

Defined in `agents/structural-reviewer.md` with frontmatter `name:
codeclone-structural-reviewer`. Read-only review protocol; does not declare
intent or modify files. The structural reviewer agent uses CodeClone MCP tools
exclusively for evidence, does not modify files or declare change intent, and
does not treat report-only signals as CI failures or vulnerability claims.

## Rules

All three ship under `plugins/cursor-codeclone/rules/`:

| File | Activation | Role |
|------|------------|------|
| `codeclone-workflow.mdc` | `alwaysApply: true` | MCP-only discipline, absolute `root`, tool preferences, memory `root` requirement |
| `change-control-gate.mdc` | `alwaysApply: true` | Hard gate: `start` before edit, `finish` before done, memory before finish when required |
| `codeclone-python.mdc` | `globs: **/*.py` | Python context: analyze before structural edits, blast radius awareness |

The change-control **skill** expands profiles and queue/promote; the
**change-control-gate** rule is the always-on prohibition layer.

### Skill contract invariants

Each skill follows these invariants:

- **MCP tools only** — no CLI or local report fallbacks
- **Absolute roots** — analysis and memory tools require absolute `root`
- **Source of truth** — report CodeClone findings as-is
- **Conservative first pass** unless the user requests deeper sensitivity
- **Workflow tools preferred** — `start_controlled_change` /
  `finish_controlled_change` for edits; atomic verify is advanced/fallback
- **Engineering Memory** — optional semantic search when server index is built;
  human approve via VS Code only

Skills are invocable via `/name` in Cursor chat (see each `SKILL.md`).

## Hooks

Documented from `hooks/hooks.json` and installers — **hook Python sources not
edited in doc-only passes.**

### Why Settings → Hooks can show "Configured Hooks (0)"

| Source | Path | Shown in Hooks UI |
|--------|------|-------------------|
| Project | `.cursor/hooks.json` | yes |
| User | `~/.cursor/hooks.json` | yes |
| Plugin manifest | `hooks/hooks.json` via `plugin.json` | **no** (may still run when plugin enabled) |

Plugin manifest commands use `python "${CURSOR_PLUGIN_ROOT}/hooks/run_hook.py"
<subcommand>"` with subcommands `pre-tool-use-gate`, `post-tool-use`,
`session-cleanup`.

### Hook events

- **preToolUse** (`Write|StrReplace|ApplyPatch|Shell`, `failClosed: true`, 5s
  timeout) — blocks when the workspace intent registry has no live **active**
  intent. Uses `codeclone.workspace_intent` (file or SQLite registry). Scope:
  - `python` (default): `.py` / `.pyi` and matching shell
  - `repo`: any path under workspace root (including `.git/**`)
  - Config: `.cursor/codeclone-hooks.json` or `CODECLONE_HOOKS_ENFORCE_SCOPE`
- **postToolUse** (`Write|StrReplace|ApplyPatch`, 5s) — injects
  `additional_context` **only when the edited path is `.py` / `.pyi`**
  (`post-tool-use-python-edit.py`).
- **stop** (`loop_limit: 1`, 5s) — optional `followup_message` when transcript
  shows `start_controlled_change` without matching finish / `intent_cleared`.

Without an authorized intent, only read-only Git inspection shell commands are
allowed; `git apply`, commits, and direct `.git/**` writes are blocked.

`enforce_scope` (`python` vs `repo`) is configured in `.cursor/codeclone-hooks.json`
or `CODECLONE_HOOKS_ENFORCE_SCOPE`.

## Distribution

- **Monorepo source:** `plugins/cursor-codeclone/`
- **Marketplace:** not in `.agents/plugins/marketplace.json` (Codex-only entry)
- **Install:** Cursor local plugin discovery (recommended) or `.cursor/` symlinks
- **Standalone releases:** ship full `plugins/codeclone/scripts/launch_mcp.py` body

## Runtime model

Additive: local MCP via `launch_mcp.py`, six skills, three rules (two
`alwaysApply` + one Python glob), optional hooks. **31** MCP tools for agents — launcher does **not**
pass `--ide-governance-channel` (VS Code adds +2 IDE-only tools and Memory
governance). New server tools from upgraded `codeclone-mcp` pass through
unfiltered.

Monorepo: `plugins/cursor-codeclone/scripts/launch_mcp.py` delegates to
`plugins/codeclone/scripts/launch_mcp.py`. Standalone releases must embed the
full launcher body.

## Read-only contract

MCP must not mutate source, baselines, analysis cache, or canonical reports.
Change-control and session tools may write ephemeral intent state
(`.codeclone/intents/` file backend by default; SQLite optional) and
optional audit rows when `audit_enabled=true`.

## Design rules

- **Cursor-native packaging** under `plugins/cursor-codeclone/`
- **Canonical MCP first** — launcher resolves `codeclone-mcp`, no tool filtering
- **Rules + skills** — `change-control-gate` always on; skills carry workflows
- **Hook safety** — `preToolUse` fail-closed; `postToolUse` / `stop` advisory
- **No hidden installs** — plugin does not patch Cursor or install Python packages

## Non-guarantees

- Cursor UI for skills/hooks may evolve independently of manifest content.
- Manual symlink installs may omit bundled rules/hooks unless the full plugin dir
  is registered.
- Hook behavior follows Cursor's hook API contract.

## Current limits

- Duplicate MCP registration (plugin `mcp.json` + manual `codeclone-mcp` entry)
  causes confusion — keep one path.
- `mcp.json` runs `python3 ./scripts/launch_mcp.py` relative to the plugin root,
  not a bare `codeclone-mcp` JSON command (the launcher resolves the binary).
- Hooks do not call MCP; they read `codeclone.workspace_intent` only.
- VS Code extension features (Memory UI governance, session/audit webviews,
  `codeclone.memory.search*` settings) are outside this plugin.

## Further reading

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/25-mcp-interface.md)
- [Engineering Memory](book/13-engineering-memory.md)
- [Structural Change Controller](book/12-structural-change-controller.md)
