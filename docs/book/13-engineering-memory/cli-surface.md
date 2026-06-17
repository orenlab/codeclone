## CLI surface

All commands live under `codeclone memory` and accept `--root` (default `.`).

| Command                                                                                | Purpose                                                   |
|----------------------------------------------------------------------------------------|-----------------------------------------------------------|
| `init [--refresh] [--dry-run] [--from-report PATH] [--no-docs] [--no-tests]`           | Create or refresh the memory store                        |
| `status`                                                                               | Schema version, counts, last ingest metadata              |
| `for-path PATH [--limit N]`                                                            | Records linked to a repo-relative path                    |
| `search QUERY [--match any\|all] [--semantic] [--active-only] [--limit N]`             | FTS search; optional semantic blend                       |
| `semantic status`                                                                      | Index availability, provider, row counts                  |
| `semantic rebuild`                                                                     | Rebuild LanceDB sidecar from memory + audit + trajectory  |
| `semantic probe [--exact-tokens] [--json]`                                             | Projection length stats (index-unit aware for trajectory) |
| `semantic search QUERY [--limit N]`                                                    | Search with semantic ranking (index required)             |
| `stale [--limit N]`                                                                    | List stale records and reasons                            |
| `vacuum`                                                                               | Retention purge per config (no dry-run flag)              |
| `coverage --scope PATH [PATH...]`                                                      | Scope coverage metrics                                    |
| `review-candidates [--limit N]`                                                        | List draft records awaiting human review                  |
| `approve RECORD_ID [--by NAME] [--i-know-what-im-doing]`                               | Promote draft → active                                    |
| `reject RECORD_ID [--by NAME] [--reason TEXT] [--i-know-what-im-doing]`                | Reject draft                                              |
| `archive RECORD_ID [--by NAME] [--i-know-what-im-doing]`                               | Archive record                                            |
| `trajectory status\|rebuild\|list\|search\|show\|agents\|anomalies\|dashboard\|export` | Trajectory projection, passport analytics, and export     |
| `jobs status\|enqueue\|run-once\|list`                                                 | Trajectory + semantic + Experience projection queue       |

### Init flags

| Flag            | Effect                                                              |
|-----------------|---------------------------------------------------------------------|
| `--dry-run`     | Build ingest batch without writing the store                        |
| `--refresh`     | Re-ingest and run staleness pass on drifted system records          |
| `--from-report` | Load a canonical report JSON path instead of cached/latest analysis |
| `--no-docs`     | Skip document-link ingest                                           |
| `--no-tests`    | Skip test-anchor ingest                                             |

### Governance (`approve` / `reject` / `archive`)

Direct CLI governance is **disabled by default**. The preferred path is the
**CodeClone VS Code Memory** view (IDE governance channel over MCP with
`--ide-governance-channel`).

For explicit human break-glass outside the IDE channel, pass
`--i-know-what-im-doing` on `approve`, `reject`, or `archive`. Attributions use
`--by` (default `human`), not `--verified-by`.

MCP agents cannot call `approve`/`reject`/`archive` on `manage_engineering_memory`.

### Trajectory analytics flags

| Subcommand  | Extra flags                                                                 |
|-------------|-----------------------------------------------------------------------------|
| `list`      | `--limit N`                                                                 |
| `search`    | `QUERY`, `--limit N`, `--match any\|all`                                    |
| `agents`    | `--include-routine`, `--json`                                               |
| `anomalies` | `--limit N`, `--include-routine`, `--json`                                  |
| `dashboard` | `--limit N`, `--include-routine`, `--json`                                  |
| `export`    | `--profile NAME`, `--out PATH`, `--allow-external-out`, `--force`, `--json` |

`--include-routine` includes routine analysis-only trajectories in aggregates
(default excludes them). Maps to MCP `filters.include_routine` on trajectory
analytics modes.

### Projection jobs flags

| Subcommand | Extra flags                                                                  |
|------------|------------------------------------------------------------------------------|
| `enqueue`  | `--force` (enqueue even when policy off or stimulus unchanged), `--no-spawn` |
| `run-once` | `--not-before ISO-8601-UTC` (defer until coalesce window elapses)            |
| `list`     | `--limit N`, `--json`                                                        |

Refs:

- `codeclone/surfaces/cli/memory.py`
- `codeclone/surfaces/cli/memory_render.py`

---
