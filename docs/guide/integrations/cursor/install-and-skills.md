# Cursor plugin

Contract: [Cursor plugin](../../../book/integrations/cursor-plugin.md).

## What ships in the plugin

| Component                          | Path                            | Purpose                                                                                      |
|------------------------------------|---------------------------------|----------------------------------------------------------------------------------------------|
| `.cursor-plugin/plugin.json`       | Manifest                        | `skills/`, `rules/`, `agents/`, `hooks/hooks.json`, `mcp.json`                               |
| `mcp.json`                         | MCP                             | `python3` + `./scripts/launch_mcp.py` — resolves `codeclone-mcp` (`.venv` → Poetry → `PATH`) |
| Skills (9)                         | `skills/*/`                     | See table below                                                                              |
| Agent                              | `agents/structural-reviewer.md` | Invoke id: **`codeclone-structural-reviewer`**                                               |
| Rules (3)                          | `rules/*.mdc`                   | See **Rules**                                                                                |
| Hooks                              | `hooks/hooks.json`              | Dispatches via `hooks/run_hook.py` (plugin manifest; optional project install)               |
| `scripts/install-project-hooks.py` | Installer                       | Writes `.cursor/hooks.json` + `.cursor/codeclone-hooks.json`                                 |
| `assets/`                          | Branding                        | Logo and icon                                                                                |

### Skills (directory vs chat command)

Chat commands use the `name:` field in each `SKILL.md` (not always the folder
name on disk):

| Folder on disk                      | Chat command (`name`)               | Primary MCP flow                                                           |
|-------------------------------------|-------------------------------------|----------------------------------------------------------------------------|
| `production-triage/`                | `/codeclone-production-triage`      | `analyze_repository` → `get_production_triage`                             |
| `codeclone-hotspots/`               | `/codeclone-hotspots`               | `analyze_repository` → hotspots / `check_*`                                |
| `blast-radius/`                     | `/codeclone-blast-radius`           | `analyze_repository` → `get_blast_radius` (read-only)                      |
| `architecture-triage/`              | `/codeclone-architecture-triage`    | Reuse run → `module_map` + impact context → ranked problems (read-only)    |
| `codeclone-review/`                 | `/codeclone-review`                 | Full review loop (conservative first)                                      |
| `codeclone-change-control/`         | `/codeclone-change-control`         | `start_controlled_change` → edit → `finish_controlled_change`              |
| `codeclone-engineering-memory/`     | `/codeclone-engineering-memory`     | `get_relevant_memory`, `query_engineering_memory`, drafts                  |
| `codeclone-implementation-context/` | `/codeclone-implementation-context` | `get_implementation_context` after `start`                                 |
| `codeclone-platform-observability/` | `/codeclone-platform-observability` | Maintainer-only: `query_platform_observability` (observer enable required) |

Codex and Claude Code plugins ship the same nine skills from `plugins/codeclone/skills/`.

## Install

### Install from the Cursor marketplace

The public storefront is
[orenlab/codeclone-cursor](https://github.com/orenlab/codeclone-cursor).

If CodeClone is already listed in your marketplace panel, select **CodeClone**,
choose user or project scope, and install it.

To expose the repository as a team marketplace:

1. Open **Cursor Dashboard → Settings → Plugins**.
2. Under **Team Marketplaces**, select **Add Marketplace**.
3. Select **Import from Repo** and enter
   `https://github.com/orenlab/codeclone-cursor`.
4. Add CodeClone, configure team access, and save.
5. Install CodeClone from Cursor's marketplace panel.

Install `codeclone[mcp]` separately so the bundled launcher can resolve
`codeclone-mcp`:

```bash
uv tool install --prerelease allow "codeclone[mcp]"
codeclone-mcp --help
```

### Local development only

Use a local symlink only while developing the plugin:

```bash
ln -sfn /path/to/codeclone/plugins/cursor-codeclone ~/.cursor/plugins/local/codeclone
```

Reload Cursor after changing the local source. Do not present this path to
normal users as the installation flow.

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

!!! note "Marketplace catalogs"
    `.agents/plugins/marketplace.json` belongs to Codex. Cursor installs this
    plugin from the `orenlab/codeclone-cursor` storefront through Cursor's own
    marketplace UI.

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

### codeclone-architecture-triage

Read-only ranked architectural problems from one stored run: module_map, metrics,
policy + structural shortlists, per-subject impact context, defect validation.
Response-local priorities only — not CodeClone findings.

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

### codeclone-implementation-context

Bounded structural, call-graph, contract, and change-control evidence from one
stored MCP run. Call after `start_controlled_change` with `intent_id` before
editing scoped Python work. Read-only — does not declare intent.

### codeclone-engineering-memory

Scope memory before edits; optional `semantic=true` on `mode=search` when
`[tool.codeclone.memory.semantic]` is enabled, the semantic sidecar is installed,
and semantic index rebuild succeeded (`manage_engineering_memory`
`action=rebuild_semantic_index` or CLI `memory semantic rebuild`). Use
`codeclone[semantic-local]` plus `embedding_provider = "fastembed"` for local
semantic-quality recall; `codeclone[semantic-lancedb]` alone supports only the
deterministic diagnostic provider. Human approve/reject: VS Code **Memory** view
(preferred) or CLI
`codeclone memory approve|reject|archive --i-know-what-im-doing` (MCP agents
cannot approve).

Full contract: [Engineering Memory](../../../book/13-engineering-memory/index.md).

### codeclone-platform-observability

**Maintainer-only** — not for users reviewing their Python repository.

Diagnose CodeClone's own runtime (MCP latency, DB cost, memory pipeline) via
`query_platform_observability` after **explicit** observer setup:

```bash
export CODECLONE_OBSERVABILITY_ENABLED=1
# restart codeclone-mcp / CLI with this env, reproduce, then query sections
```

Without enablement the tool returns `status=disabled` or `no_store`. Never treat
observer metrics as repository quality or edit authorization.

Playbook: [Maintainer workflow](../../../guide/observability/maintainer-workflow.md).

## Agent

### codeclone-structural-reviewer

Defined in `agents/structural-reviewer.md` (`name: codeclone-structural-reviewer`).
Read-only MCP evidence only; no edits or intent; report-only signals are not CI
failures or vulnerability claims.

## Distribution

- **Monorepo source:** `plugins/cursor-codeclone/`
- **Marketplace source:** `https://github.com/orenlab/codeclone-cursor`
- **Install:** Cursor marketplace panel; local symlink only for development
- **Standalone releases:** ship full `plugins/codeclone/scripts/launch_mcp.py` body

## Runtime model

Additive: local MCP via `launch_mcp.py`, nine skills, three rules (two
`alwaysApply` + one Python glob), optional hooks. The full default agent MCP
surface is passed through — the launcher does **not**
pass `--ide-governance-channel` (VS Code adds +2 IDE-only tools and Memory
governance). New server tools from upgraded `codeclone-mcp` pass through
unfiltered.

Monorepo: `plugins/cursor-codeclone/scripts/launch_mcp.py` delegates to
`plugins/codeclone/scripts/launch_mcp.py`; standalone releases must embed the full launcher body.
