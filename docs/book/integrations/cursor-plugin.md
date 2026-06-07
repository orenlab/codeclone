<!-- doc-scope: Cursor Plugin contract. class: contract max-lines: 150 -->
# Cursor Plugin

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
- **stop** (`loop_limit: 1`, 5s) — optional `followup_message` when the
  workspace intent registry still has **own or recoverable Cursor** non-terminal
  intents (active, queued, violated, expanded). Foreign active/stale intents
  from other agents are ignored — they require coordination, not
  `manage_change_intent(clear)` from this session. Transcript JSONL is a
  fallback only when registry read fails; it counts `CallMcpTool` workflow
  events, not raw substring matches.

Without an authorized intent, only read-only Git inspection shell commands are
allowed; `git apply`, commits, and direct `.git/**` writes are blocked.

`enforce_scope` (`python` vs `repo`) is configured in `.cursor/codeclone-hooks.json`
or `CODECLONE_HOOKS_ENFORCE_SCOPE`.


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

- [MCP usage guide](../../guide/mcp/README.md)
- [MCP interface contract](../25-mcp-interface/index.md)
- [Engineering Memory](../13-engineering-memory/index.md)
- [Structural Change Controller](../12-structural-change-controller/index.md)
