# CodeClone for Cursor

Cursor plugin for [CodeClone](https://orenlab.github.io/codeclone/) —
deterministic structural analysis for Python repositories.

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

- **CodeClone MCP Rules** (`alwaysApply`) — how to use the MCP server correctly:
  tool preferences, absolute roots, source-of-truth discipline.
- **Python Context** (glob: `**/*.py`) — auto-triggers when Python files are in
  context: run analysis before structural changes, check blast radius, do not
  introduce regressions.

---

## Hooks

- **Post-edit reminder** (`afterFileEdit`) — when a Python file is edited,
  reminds the agent to re-run analysis and check intent status.
- **Session cleanup** (`stop`) — at session end, warns if change intents were
  declared but not cleared.

---

## MCP Server

The plugin bundles a stdio-based `codeclone-mcp` server configuration via
`python3 ./scripts/launch_mcp.py` (workspace `.venv` → Poetry env → `PATH`).
The server exposes all 28 MCP tools (full passthrough). Skills and rules steer
agents toward the documented workflow; the plugin does not filter tools at the
transport layer.

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
  caches, or report artifacts. Agents reach the full MCP server (28 tools),
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
