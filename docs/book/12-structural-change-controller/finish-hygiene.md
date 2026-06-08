## Workspace hygiene and registry consistency

Three independent contours (do not collapse):

```text
status     = persisted registry lifecycle
ownership  = runtime view (PID / TTL / lease)
hygiene    = git working tree ∩ declared scope
permission = edit_allowed (with status gate)
```

**Lazy intent closure:** agent-facing registry reads (`list_workspace`,
declare/start workspace refresh) close eligible non-terminal intents using a
**lazy-close predicate** (`for_lazy_close=True`). Lease-only staleness with valid
TTL is not closed on read. **Orphaned** (dead PID) intents stay recoverable until
TTL expiry or explicit `gc_workspace` — lazy close does not purge them.

**Explicit GC:** `gc_workspace` performs cleanup/purge in one atomic transaction
using a broader removal predicate. Lazy close and GC share intent lifecycle
concepts, but **not** an identical close predicate.

Registry I/O is serialized with cross-process locks; SQLite `gc()` is one
atomic scan→close→purge transaction.

**Continuing known WIP:** when uncommitted changes already overlap your declared
scope, default `dirty_scope_policy="block"` returns workflow `status: "blocked"`.
Pass `dirty_scope_policy="continue_own_wip"` only to resume known dirty scope
when **no** live foreign dirty overlap exists (`foreign_dirty_overlaps` empty).
Finish must still prove all declared-scope dirty paths via `changed_files` or
`diff_ref`.

**Start blocking:** when foreign active/stale scope overlap is unresolved
(without `on_conflict="queue"`) or scoped hygiene detects dirty paths in
`allowed_files`, `start_controlled_change` returns workflow `status: "blocked"`,
`edit_allowed: false`, and populated `workspace` / `workspace_hygiene` payloads.
`blocked` is workflow-only — never persisted registry lifecycle status.

**Finish hygiene gate:** see [finish_controlled_change](finish-controlled-change.md)
for the full pipeline. By default only `missing_evidence` and
`foreign_dirty_overlap` set `blocks_finish`. With
[strict finish mode](../10-config-and-defaults.md#mcp-session-and-change-control-hygiene)
enabled, `own_unscoped_dirty` may also block. Out-of-scope unattributed dirt is
advisory and may elevate the top-level status to `accepted_with_external_changes`
without failing verify.
**Queued** foreign intents do not populate `foreign_dirty_overlaps`.

Declare **new files** in `allowed_files` at `start`, not only in
`allowed_related`. Finish always attaches `workspace_hygiene_after` (scoped
hygiene + repo-level `workspace_dirty_summary`) on verify paths that reach
hygiene evaluation.

**List workspace:** `manage_change_intent(action="list_workspace")` attaches
repo-level `workspace_dirty_summary` only (bounded dirty path sample). Scoped
`workspace_hygiene.blocks_edit` applies only to start/finish. When recoverable
intents exist, the response includes `recovery_available` (each entry may show
`run_available: false` after MCP restart) and top-level `recovery_next_step`.

### Finish hygiene: what blocks vs what informs

Finish hygiene reconciles **agent evidence with git** and the **start-time dirty
snapshot**. It is not honor-system.

**Blocking** (`blocks_finish: true`, top-level `reason: workspace_hygiene`,
`user_action_required: true`) happens only for:

| `finish_block_reason`   | Meaning                                                                                      | Agent action                                                                               |
|-------------------------|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| `missing_evidence`      | Git is dirty inside declared scope but the path is missing from `changed_files` / `diff_ref` | Add every in-scope dirty path to evidence or revert                                        |
| `foreign_dirty_overlap` | A **live** foreign active/stale intent previously declared the same **in-scope** path        | Coordinate (queue/promote/clear foreign intent), stash/commit foreign WIP, or narrow scope |
| `own_unscoped_dirty`    | Unattributed out-of-scope dirty when strict finish mode is enabled (see env overrides)       | Reconcile out-of-scope dirt, widen scope, or unset strict mode                             |

**Non-blocking (advisory)** — surfaced on `workspace_hygiene_after` (path lists in
`dirty_attribution` when `detail_level="full"`), but **do not** set
`finish_block_reason` and **do not** feed `files_for_scope_check`:

| Field                                  | Meaning                                                                                 |
|----------------------------------------|-----------------------------------------------------------------------------------------|
| `preexisting_unscoped_dirty`           | Out-of-scope dirty at `start`, unchanged since — informational                          |
| `new_unattributed_unscoped_dirty`      | Out-of-scope dirty appeared after `start`, not foreign-attributed — peer/context signal |
| `modified_unattributed_unscoped_dirty` | Out-of-scope dirty existed at `start` but content changed — peer/context signal         |
| `unknown_unattributed_unscoped_dirty`  | No usable start snapshot for comparison — conservative classification only              |
| `foreign_attributed_outside_scope`     | Out-of-scope dirty owned by foreign active/stale intent — ignored for your finish       |
| `dirty_paths_outside_scope`            | All out-of-scope dirty paths — drives `external_changes` when verify is `accepted`      |

`own_unscoped_dirty` and `unattributed_unscoped_dirty` are **legacy aliases** for
the union of unattributed out-of-scope paths. They are **not** proof that the
current agent owns those edits and **do not** block finish.

**Recoverable** foreign intents (dead PID) do **not** populate
`foreign_attributed_outside_scope`. **Queued** foreign intents do **not**
populate `foreign_dirty_overlaps`.

When verify returns plain `accepted` but `dirty_paths_outside_scope` is
non-empty, finish elevates the top-level status to
`accepted_with_external_changes` and attaches:

```json
"external_changes": {"count": N, "sample": ["path", "..."], "truncated": false}
```
