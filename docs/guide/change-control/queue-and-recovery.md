<!-- doc-scope: Queue and recovery recipe. class: guide max-lines: 120 -->

# Queue & recovery

## Multi-agent queue

```
start_controlled_change(scope={...}, on_conflict="queue")
  -> wait for foreign intent to clear
  -> manage_change_intent(action="promote", intent_id=...)
  -> edit within scope
  -> finish_controlled_change(...)
```

## Workspace hygiene (guide summary)

Three contours: **status** (registry lifecycle), **ownership** (PID/TTL),
**hygiene** (git ∩ scope), **permission** (`edit_allowed`).

- **`dirty_scope_policy`:** `continue_own_wip` resumes known WIP in scope when no
  foreign overlap; finish still needs evidence.
- **`gc_workspace`:** explicit GC vs lazy close on read — different predicates.
- **Blocking finish:** `missing_evidence`, `foreign_dirty_overlap`, and (when
  [strict finish mode](../../book/10-config-and-defaults.md#mcp-session-and-change-control-hygiene)
  is enabled) `own_unscoped_dirty`.

Normative tables: [Finish hygiene](../../book/12-structural-change-controller/finish-hygiene.md),
[payload semantics](../../book/12-structural-change-controller/payload-semantics.md).

Recovery: `manage_change_intent(action=recover|reset_workspace)` when MCP hints
`recovery_available`.
