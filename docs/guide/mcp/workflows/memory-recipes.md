<!-- doc-scope: MCP memory recipes. class: guide max-lines: 130 -->
# Engineering Memory recipes (MCP)

Ranked scope context and governed drafts — **not** a second analyzer. Normative
tool shapes: [Engineering Memory MCP surface](../../../book/13-engineering-memory/mcp-surface.md).

Session-local review markers live in [Session & coverage](session-and-coverage.md).

## 1. Bootstrap before first scoped retrieval

When the store is missing, default `mcp_sync_policy=bootstrap_if_missing` ingests
from the latest MCP run on the first scoped `get_relevant_memory`.

| Step | Tool / action |
|------|----------------|
| Analyze | `analyze_repository(root=<abs>)` |
| Optional explicit ingest | `manage_engineering_memory(action=refresh_from_run, root=<abs>)` |
| Offline init | `codeclone memory init` (CI/offline; same ingest contract) |

## 2. Scope context after `start_controlled_change`

Call only after `edit_allowed=true`. **`root` is required** (same absolute path
as analysis).

```text
get_relevant_memory(root=<abs>, intent_id=<id>)
  # or scope=["path/to/file.py", ...]
```

Read `memory_sync`, stale warnings, and `contradiction_note` entries before editing.
Do not treat `draft` / `inferred` rows as established facts.

## 3. Draft observations during the cycle

```text
manage_engineering_memory(
  action=record_candidate,
  root=<abs>,
  record_type=risk_note | change_rationale | ...,
  statement="<one durable fact>",
  subject_path="path/to/main/file.py",
)
```

Agents **cannot** `approve` / `reject` / `archive` via MCP. Humans promote drafts
in the VS Code Memory view or with `codeclone memory approve`.

## 4. Finish proposals

On accepted finish:

```text
finish_controlled_change(..., propose_memory=true)
```

Returns `memory_candidates`, `memory_staleness`, `memory_coverage_delta`, and may
enqueue projection rebuild when configured.

## 5. Search and drill-down

| Goal | Call |
|------|------|
| Keyword search | `query_engineering_memory(mode=search, query=..., root=<abs>, filters={match_mode: any\|all})` |
| Semantic blend | same + `semantic=true` when semantic index is built |
| One path | `query_engineering_memory(mode=for_path, path=..., root=<abs>)` |
| Trajectory preview | `query_engineering_memory(mode=trajectory_get, intent_id=..., root=<abs>)` |
| Playbook | `help(topic=engineering_memory)` |

## 6. Semantic index maintenance

When `[tool.codeclone.memory.semantic] enabled=true`:

```text
manage_engineering_memory(action=rebuild_semantic_index, root=<abs>)
```

Contract: [Semantic search](../../../book/13-engineering-memory/search-semantic.md).

---
