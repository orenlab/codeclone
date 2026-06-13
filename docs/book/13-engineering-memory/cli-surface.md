## CLI surface

All commands live under `codeclone memory` and accept `--root` (default `.`).

| Command                                                                                | Purpose                                               |
|----------------------------------------------------------------------------------------|-------------------------------------------------------|
| `init [--refresh] [--dry-run]`                                                         | Create or refresh the memory store                    |
| `status`                                                                               | Schema version, counts, last ingest metadata          |
| `for-path PATH [--limit N]`                                                            | Records linked to a repo-relative path                |
| `search QUERY [--match any\|all] [--semantic] [--active-only] [--limit N]`             | FTS search; optional semantic blend                   |
| `semantic status`                                                                      | Index availability, provider, row counts              |
| `semantic rebuild`                                                                     | Rebuild LanceDB sidecar from memory + audit           |
| `semantic search QUERY [--limit N]`                                                    | Search with semantic ranking (index required)         |
| `stale [--limit N]`                                                                    | List stale records and reasons                        |
| `vacuum [--dry-run]`                                                                   | Retention purge per config                            |
| `coverage --scope PATH [PATH...]`                                                      | Scope coverage metrics                                |
| `review-candidates [--limit N]`                                                        | List draft records awaiting human review              |
| `approve RECORD_ID [--verified-by NAME]`                                               | Promote draft → active                                |
| `reject RECORD_ID [--reason TEXT]`                                                     | Reject draft                                          |
| `archive RECORD_ID [--reason TEXT]`                                                    | Archive record                                        |
| `trajectory status\|rebuild\|list\|search\|show\|agents\|anomalies\|dashboard\|export` | Trajectory projection, passport analytics, and export |
| `jobs status\|enqueue\|run-once\|list`                                                 | Trajectory + semantic + Experience projection queue   |

Human governance (`approve`, `reject`, `archive`) is available through the
**CodeClone VS Code Memory** view (IDE governance channel) and the
`codeclone memory approve|reject|archive` CLI. MCP agents cannot call
`approve`/`reject`/`archive` on `manage_engineering_memory`.

Refs:

- `codeclone/surfaces/cli/memory.py`
- `codeclone/surfaces/cli/memory_render.py`

---
