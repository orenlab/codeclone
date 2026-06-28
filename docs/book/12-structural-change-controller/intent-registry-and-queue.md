## Workspace Intent Registry

`manage_change_intent` also supports workspace actions for multi-agent
coordination:

- `list_workspace`: list active workspace intent records from all agents for a
  repository root. Includes `recovery_available` (with `run_available` and
  per-candidate `hint`), `recovery_next_step` when recoverable intents exist,
  and workspace counters such as `stale_count`, `orphaned_count`, and
  `total_agents`.
- `renew`: refresh the active lease before long edits or test runs.
- `gc_workspace`: remove expired, orphaned, or corrupted registry records.
- `recover`: explicitly reclaim a recoverable intent when the caller has the
  matching run and report digest in the current MCP session.
- `reset_workspace`: reset an own intent or remove expired/recoverable
  registry records. Foreign active and foreign stale intents are rejected
  and require coordination.

Registry records live under `.codeclone/intents/` by default (one JSON
file per intent) and are protected with a SHA-256 integrity digest over
canonical JSON. Repositories may opt into a SQLite backend instead:

```toml
[tool.codeclone]
intent_registry_backend = "sqlite"
intent_registry_path = ".codeclone/db/intents.sqlite3"
```

Environment overrides for registry keys:
[10-config Environment variable overrides](../10-config-and-defaults.md#environment-variable-overrides)
(workspace intent registry table).

The SQLite backend stores the same signed JSON payloads in WAL mode; integrity
and validation rules are unchanged. Unlike the file backend, SQLite keeps
closed intents (`clean`, `expired`, `orphaned`) for audit and purges them only
after `intent_registry_retention_days` (default `14`, any positive value; no
edition cap). Managed/hosted retention with backup and compliance is a roadmap
Team/Enterprise option; see [Plans and Retention](../../plans-and-retention.md).

This detects accidental corruption, not malicious tampering by a user with write
access. Conflicts are advisory: hard overlap means two agents claimed the same
primary file; soft overlap means primary files overlap related context.

Each registry record has a TTL and a shorter renewable lease. TTL is the hard
maximum lifetime of the record (default 3600s). The lease is the ownership
freshness signal (default 300s, max 600s): active MCP interactions auto-renew
it, while detached processes stop renewing and transition through ownership
states.

??? info "Ownership classification"

    | State            | PID alive | Lease valid | Meaning                                              |
    |------------------|-----------|-------------|------------------------------------------------------|
    | `own_active`     | own       | yes         | This session's active intent                         |
    | `own_stale`      | own       | no          | This session's intent with expired lease             |
    | `foreign_active` | foreign   | yes         | Another live process, active lease — coordinate      |
    | `foreign_stale`  | foreign   | no          | Another live process, expired lease — coordinate     |
    | `recoverable`    | dead      | —           | Owning process is dead; safe to reclaim              |
    | `expired`        | —         | —           | TTL exceeded; eligible for garbage collection        |

    A foreign active or foreign stale record should be coordinated with the
    user; CodeClone does not ask agents to kill the owning process. Only
    `recoverable` intents (dead PID) can be reclaimed without user
    coordination.

### Cursor local enforcement (optional)

The Cursor plugin can install project hooks (`.cursor/hooks.json`) that run a
fail-closed `preToolUse` gate before `Write`, `StrReplace`, `ApplyPatch`, and
`Shell`. The gate calls the read-only API
`codeclone.workspace_intent.evaluate_workspace_edit_gate`, which loads the same
registry backend as MCP (`file` or `sqlite` per `[tool.codeclone]`). It does not
lazy-close records, create registry files, or read plugin-local marker files.

| Registry signal                                                       | Hook behavior                                                       |
|-----------------------------------------------------------------------|---------------------------------------------------------------------|
| Live `active` intent (any agent; lease/TTL rules match MCP ownership) | Authorize repository writes and non–read-only shell                 |
| `queued` only                                                         | Deny — queued intents are visible but not editable locally          |
| No active intent / registry error                                     | Deny file tools; allow only read-only Git inspection shell commands |

Hooks require `codeclone` in the Python interpreter referenced by
`.cursor/hooks.json` (typically the project venv). Install:
`plugins/cursor-codeclone/scripts/install-project-hooks.py`. See
[Cursor plugin guide](../../guide/integrations/cursor/install-and-skills.md) and
[Cursor plugin contract](../integrations/cursor-plugin.md).

## Workspace Relations

`detect_conflicts` classifies the relationship between a new intent and existing
workspace intents. Beyond edit-overlap detection (hard and soft conflicts),
the classifier distinguishes forbidden-scope relationships:

| Relation                  | Meaning                                             |
|---------------------------|-----------------------------------------------------|
| `edit_overlap`            | Both agents claim the same files (hard or soft)     |
| `foreign_excludes_target` | Foreign `forbidden` matches current `allowed_files` |
| `target_excludes_foreign` | Current `forbidden` matches foreign `allowed_files` |

Absence of a relation entry means disjoint scope.

The `declare` response includes a `workspace_relations` field alongside the
existing `concurrent_intents`. `concurrent_intents` continues to contain only
edit overlaps for backward compatibility; `workspace_relations` provides the
full classification including forbidden-scope signals.

This allows agents to distinguish three cases that were previously
indistinguishable:

1. No overlap at all (disjoint).
2. No edit overlap, but the foreign agent explicitly excludes the current
   agent's target files (`foreign_excludes_target`) — a positive coordination
   signal.
3. No edit overlap, but the current agent explicitly excludes the foreign
   agent's target files (`target_excludes_foreign`).

## Intent Queue

When multiple agents target overlapping scope, `manage_change_intent` supports
an advisory queue so a blocked agent can register its intent without failing.

### Declare with queue

`manage_change_intent(action="declare", on_conflict="queue")` first attempts a
normal declare. If `detect_conflicts` finds overlapping foreign active intents,
it downgrades the already-registered intent to `queued` instead of returning an
error.

A queued intent:

- Is visible in `list_workspace` as a workspace record with `status="queued"`.
- Does **not** own scope — conflict detection skips queued records.
- Does **not** pin the before-run — long waits may cause eviction from bounded
  run history.
- Cannot pass `check_patch_contract(mode="verify")` or
  `check_patch_contract(mode="budget")` with `edit_allowed=true`.
- Can be cleared via `manage_change_intent(action="clear")`.

The declare response includes `blocked_by` (list of blocking intents with
`intent_id`, `agent_pid`, `ownership`, `overlapping_files`) and
`queue_position` (deterministic ordering by `declared_at_utc`, then
`intent_id`).

### Promote

`manage_change_intent(action="promote", intent_id=...)` transitions a queued
intent to active:

1. Validates the intent has `status="queued"`.
2. Resolves the before-run — if evicted, returns `status="unverified"` with
   `reason="before_run_evicted"` and a `next_step` hint.
3. Re-checks workspace conflicts. If conflicts persist, returns `status="queued"`
   with `blocking_count` and `blocked_by` without changing state.
4. On success: sets status to `active`, pins the run, renews the lease, and
   updates the workspace record.

### Queue semantic invariants

- `queued` is a lifecycle status, not an ownership classification. Ownership
  (`own_active`, `foreign_active`, etc.) and status (`active`, `queued`) are
  orthogonal.
- Queued intents do not block other agents. `_detect_scope_state` skips records
  with `status == "queued"`.
- Queue position is deterministic: sorted by `declared_at_utc`, then
  `intent_id` as tiebreaker.

### Audit events

| Event                  | When                         |
|------------------------|------------------------------|
| `intent.queued`        | Declare downgrades to queued |
| `intent.promoted`      | Promote succeeds             |
| `intent.queue_blocked` | Promote blocked by conflicts |
