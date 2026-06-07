### Projection rebuild jobs (schema 1.3)

Trajectory + semantic projections can be rebuilt asynchronously via a
coalesced job row in Engineering Memory SQLite (`memory_projection_jobs`).
Default policy is **`off`**; opt in with:

```toml
[tool.codeclone.memory]
projection_rebuild_policy = "enqueue_when_stale"  # off | enqueue_when_stale
```

| Surface           | Command / action                                                                  |
|-------------------|-----------------------------------------------------------------------------------|
| CLI status        | `codeclone memory jobs status --root .`                                           |
| CLI enqueue       | `codeclone memory jobs enqueue --root . [--force] [--no-spawn]`                   |
| CLI worker        | `codeclone memory jobs run-once --root .`                                         |
| MCP enqueue       | `manage_engineering_memory(action=enqueue_projection_rebuild)`                    |
| MCP status        | `manage_engineering_memory(action=projection_rebuild_status)`                     |
| MCP worker        | `manage_engineering_memory(action=run_projection_jobs_once)`                      |
| MCP auto (finish) | When policy ≠ `off`, accepted `finish_controlled_change` enqueues + spawns worker |

Jobs never run in CI environments (`CI`, `GITHUB_ACTIONS`, …). Sync rebuild
escape hatches remain: `rebuild_trajectories` / `rebuild_semantic_index`.
