# CodeClone for Cursor

Cursor plugin for [CodeClone](https://orenlab.github.io/codeclone/) —
**Structural Change Controller for AI-assisted Python development**.

Brings baseline-aware triage, blast radius inspection, change control, and
structural review into Cursor's AI workflow through Skills, Rules, Hooks, and
the `codeclone-mcp` server.

---

## Requirements

- Cursor with plugin support
- Python workspace
- `codeclone-mcp` launcher (`codeclone >= 2.0.0`)

### Install the launcher

```bash
uv tool install "codeclone[mcp]"
```

Verify:

```bash
codeclone-mcp --help
```

---

## Skills

| Skill                 | Command                        | Purpose                                                                |
|-----------------------|--------------------------------|------------------------------------------------------------------------|
| **Production Triage** | `/codeclone-production-triage` | Quick health snapshot: score, hotspots, regressions, next action       |
| **Hotspots**          | `/codeclone-hotspots`          | Fast metric check: complexity, coupling, cohesion, clones              |
| **Blast Radius**      | `/codeclone-blast-radius`      | Structural impact of changing specific files                           |
| **Review**            | `/codeclone-review`            | Full structural review session with baseline-aware triage              |
| **Change Control**    | `/codeclone-change-control`    | Intent-first edit workflow: declare, blast radius, edit, verify, clear |
| **Engineering Memory** | `/codeclone-engineering-memory` | Scope memory before edits, search, draft `record_candidate`, finish proposals |

### Typical flow

1. `/codeclone-production-triage` — understand the current state.
2. `/codeclone-blast-radius` — check impact before editing.
3. `/codeclone-change-control` — edit with full structural verification.

---

## Agent

**Structural Reviewer** (`codeclone-structural-reviewer`) — a code review agent that uses CodeClone MCP tools to
assess clone risk, complexity hotspots, coupling, and blast radius. Reports
deterministic findings with file paths and evidence, not opinions.

---

## Rules

Three rules ship in `rules/` (load via plugin discovery, not only manual symlinks):

| File | Activation | Role |
|------|------------|------|
| `codeclone-workflow.mdc` | always | MCP-only, absolute `root`, tool preferences |
| `change-control-gate.mdc` | always | Hard gate: `start` / `finish`, memory before finish when required |
| `codeclone-python.mdc` | `**/*.py` | Analyze before structural edits; respect blast radius |

Chat skill ids use the `name:` field in each `SKILL.md` (folders `production-triage/`
and `blast-radius/` differ from ids `codeclone-production-triage` and
`codeclone-blast-radius`).

---

## Hooks

Cursor **Settings → Hooks** lists only **project** (`.cursor/hooks.json`) and
**user** (`~/.cursor/hooks.json`) configs — not plugin-manifest hooks. Install
project hooks so the IDE shows them and they run in this repo:

```bash
# from the codeclone repo root (creates .cursor/hooks.json + .cursor/codeclone-hooks.json)
uv run python plugins/cursor-codeclone/scripts/install-project-hooks.py

# gate all repository files (not only Python)
uv run python plugins/cursor-codeclone/scripts/install-project-hooks.py --enforce-scope repo

# any other Python project
uv run python plugins/cursor-codeclone/scripts/install-project-hooks.py /path/to/project
```

**Enforcement scope** (`.cursor/codeclone-hooks.json` or `CODECLONE_HOOKS_ENFORCE_SCOPE`):

| Mode | Value | Blocks without `start_controlled_change` |
|------|-------|------------------------------------------|
| Python only | `python` (default) | `.py` / `.pyi` under the workspace |
| Full repo | `repo` | any write under the workspace root |

Hook behavior:

- **Change-control gate** (`preToolUse`, `failClosed`) — `permission: deny` when
  CodeClone's configured workspace intent registry has no live active intent.
  The hook uses the public `codeclone.workspace_intent` read-only API, so file
  and SQLite registry backends behave the same. Without an authorized intent,
  direct repository file writes are blocked, including `.git/**`; only read-only
  Git inspection shell commands are allowed.
- **Python write reminder** (`postToolUse`) — advisory `additional_context` only
  when the edited path is `.py` / `.pyi` (matcher fires on all writes; script
  filters to Python).
- **Session cleanup** (`stop`) — optional `followup_message` for unclosed intents.

Reload Cursor or reopen the workspace after installing. Project hooks require a
**trusted** workspace.

---

## MCP Server

The plugin bundles a stdio-based `codeclone-mcp` server configuration via
`python3 ./scripts/launch_mcp.py` (workspace `.venv` → Poetry env → `PATH`).
The server exposes all **31** MCP tools for agents (full passthrough; no
`--ide-governance-channel`). Skills and rules steer agents toward the documented
workflow; the plugin does not filter tools at the transport layer. IDE-only
`get_workspace_session_stats` / `get_controller_audit_trail` require the VS Code
extension launcher.

## Distribution

- **Monorepo source:** `plugins/cursor-codeclone/`
- **Not in** `.agents/plugins/marketplace.json` (Codex-only local marketplace)
- **Standalone releases:** embed the full launcher from
  `plugins/codeclone/scripts/launch_mcp.py`; the monorepo uses a thin delegator

---

## Local development

Symlink the plugin directory for local testing:

```bash
ln -s /path/to/codeclone/plugins/cursor-codeclone ~/.cursor/plugins/local/codeclone
```

---

## Design decisions

- **No second truth model** — health, findings, and drift come exclusively from
  `codeclone-mcp` and canonical report semantics.
- **Repository read-only** — the plugin never edits source files, baselines,
  caches, or report artifacts. Agents reach the full MCP server (31 tools),
  including change-control and session tools, via the bundled stdio launcher.
- **Intent-first edits** — the change control skill enforces the full declare /
  blast-radius / edit / verify / clear cycle.
- **Deterministic, not opinionated** — the agent reports what CodeClone finds,
  not what it thinks.

---

## Documentation

- [CodeClone documentation](https://orenlab.github.io/codeclone/)
- [MCP usage guide](https://orenlab.github.io/codeclone/mcp/)
- [MCP interface contract](https://orenlab.github.io/codeclone/book/20-mcp-interface/)
