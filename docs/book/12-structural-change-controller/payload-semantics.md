## Change-control payload semantics

This section supplements the workflow descriptions above. It does not repeat tool
lists or atomic step sequences.

### Scope path matching

Declare **repo-relative file paths** in `allowed_files` and `allowed_related`.
Glob patterns such as `docs/**` are **not** valid scope entries for scope
`check` — each changed path must appear literally in the declared lists.

| Mechanism | Matching rule |
|-----------|---------------|
| Scope `check` (`unexpected_files`) | Exact membership in `allowed_files` or `allowed_related` |
| Start/finish hygiene (in-scope dirty) | Exact path **or** directory prefix (`docs/book` covers `docs/book/foo.md`) |
| Verify regression attribution | `fnmatchcase` on declared patterns (may differ from scope check) |
| `forbidden` | `fnmatchcase` on declared patterns |

List every path you create, modify, or delete in finish evidence
(`changed_files` or `diff_ref`).

### `structural_delta.health_delta` vs receipt `health.delta`

Verify compares the intent's **before-run** to the explicit **after-run** via
`compare_runs`. `structural_delta` mirrors that comparison:

```json
"before": {"run_id": "14d82d39", "health": 90},
"after": {"run_id": "74cb3c0e", "health": 88},
"structural_delta": {
"verdict": "regressed",
"health_delta": -2,
"regressions": ["...new finding ids..."]
}
```

| Field                            | Source                                             | Meaning                                              |
|----------------------------------|----------------------------------------------------|------------------------------------------------------|
| `verification.before` / `.after` | Intent before-run vs `after_run_id`                | Run refs used for patch contract                     |
| `structural_delta.health_delta`  | `health_after - health_before` from `compare_runs` | **Patch delta** between those two stored runs        |
| `receipt.health.delta`           | After-run summary vs trusted baseline              | **Repository drift** signal in the receipt narrative |

Patch deltas are run-relative, not baseline-novelty-relative. A finding absent
from the clean before-run and present in the after-run is a patch regression
even when its fingerprint is `novelty="known"` against the trusted baseline.

If `before.run_id == after.run_id` for `python_structural` or
`governance_config` profiles, verify returns `status: "unverified"` with
`reason: "after_run_not_new"` — run a fresh post-edit analysis and pass the new
`after_run_id`. For documentation-only patches the identical-run case is not
structurally gated the same way.

Negative `health_delta` sets `structural_delta.verdict` to `"regressed"` (or
`"mixed"` when improvements coexist). It does **not** by itself set
`verification.status` to `"violated"` — blocking comes from intent-scoped
finding regressions, gate worsening attributable to the patch, scope
violations, or baseline-abuse signals. Agents should still surface
`health_delta < 0` in review text. Accepted verify may include
`health_regression_advisory`. Claim Guard warns and violates regression-free
claims when `patch_health_delta < 0` (passed automatically by
`finish_controlled_change`; explicit on atomic `validate_review_claims`).

### Multi-agent hygiene (who blocks whom)

Hygiene reads the **shared git working tree**, not per-agent sandboxes.

| Actor                                                                              | Trigger                                | Start                                                                                                    | Finish                                                           |
|------------------------------------------------------------------------------------|----------------------------------------|----------------------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| **Foreign active/stale** intent on overlapping scope                               | `concurrent_intents`                   | `status: "blocked"` (coordination)                                                                       | —                                                                |
| **Any** uncommitted dirty file in your `allowed_files`                             | `workspace_hygiene.blocks_edit`        | `edit_allowed: false` (unless `dirty_scope_policy="continue_own_wip"` and no live foreign dirty overlap) | —                                                                |
| Dirty in scope **not** listed in `changed_files` / `diff_ref` (git reconciliation) | `unacknowledged_dirty_in_scope`        | —                                                                                                        | **`finish_block_reason: missing_evidence`** (blocks finish)      |
| Dirty **outside** declared scope, already dirty at `start` and unchanged           | `preexisting_unscoped_dirty`           | —                                                                                                        | Advisory only                                                    |
| Dirty **outside** declared scope, appeared after `start`, not foreign-attributed   | `new_unattributed_unscoped_dirty`      | —                                                                                                        | Advisory — may appear in `external_changes`                      |
| Dirty **outside** declared scope, changed after `start`, not foreign-attributed    | `modified_unattributed_unscoped_dirty` | —                                                                                                        | Advisory — may appear in `external_changes`                      |
| Dirty **outside** declared scope, no usable start snapshot                         | `unknown_unattributed_unscoped_dirty`  | —                                                                                                        | Advisory classification only                                     |
| Foreign dirty **outside** your scope (other agent's paths)                         | `foreign_attributed_outside_scope`     | —                                                                                                        | **ignored** — does not block finish                              |
| **Live** foreign intent previously declared overlapping dirty paths in your scope  | `foreign_dirty_overlaps`               | Contributes to `blocks_edit` at start                                                                    | **`finish_block_reason: foreign_dirty_overlap`** (blocks finish) |

Recoverable, expired, terminal, or **queued** foreign records **do not**
populate `foreign_dirty_overlaps`. A queued peer does not block finish for an
active agent.

**Foreign attribution at finish:** only **`foreign_active`** and
**`foreign_stale`** intents (live owning PID, foreign to this session) may
populate `foreign_attributed_outside_scope`. **`Recoverable`** intents (dead
owning PID) do **not** grant foreign attribution — treat their dirty paths like
ordinary workspace dirt unless scope is widened or changes reverted.

**Finish hygiene payload fields** (on `workspace_hygiene` / `workspace_hygiene_after`
when finish is hygiene-gated):

For hygiene, `detail_level` is effectively binary: `summary` and `normal` return
`counts`, overlap lists, and blocking fields only; pass `detail_level="full"` for
`dirty_attribution`, path classification arrays, and expanded `dirty_snapshot`.

| Field                                      | Meaning                                                                                                                                 |
|--------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| `unacknowledged_dirty_in_scope`            | In-scope git dirty missing from finish evidence                                                                                         |
| `preexisting_unscoped_dirty`               | Out-of-scope git dirty that existed at `start` and did not change — informational, non-blocking                                         |
| `unattributed_unscoped_dirty`              | Union of unattributed out-of-scope paths — **advisory**, not blocking                                                                   |
| `own_unscoped_dirty`                       | Legacy alias for `unattributed_unscoped_dirty`; not proof of ownership                                                                  |
| `new_unattributed_unscoped_dirty`          | Out-of-scope dirty path appeared after `start`                                                                                          |
| `modified_unattributed_unscoped_dirty`     | Out-of-scope dirty path existed at `start` but changed afterward                                                                        |
| `unknown_unattributed_unscoped_dirty`      | Out-of-scope dirty path cannot be compared with a start snapshot                                                                        |
| `foreign_attributed_outside_scope`         | Out-of-scope git dirty owned by foreign active/stale intent — informational, non-blocking                                               |
| `dirty_attribution`                        | Per-path attribution (`detail_level="full"` only)                                                                                       |
| `dirty_snapshot` / `dirty_snapshot_status` | Snapshot summary; expanded detail with `detail_level="full"`                                                                            |
| `files_for_scope_check`                    | Agent evidence only — paths passed to scope `check` (out-of-scope dirt does not expand scope)                                           |
| `finish_block_reason`                      | `missing_evidence`, `foreign_dirty_overlap`, or (when `CODECLONE_STRICT_FINISH` is truthy) `own_unscoped_dirty` when `blocks_finish` is true |
| `external_changes`                         | On finish response when verify is `accepted` but out-of-scope dirty remains — top-level status becomes `accepted_with_external_changes` |

**Typical two-agent overlap on `pkg/a.py`:**

1. Agent A (active intent) edits → working tree dirty on `pkg/a.py`.
2. Agent B calls `start` on the same path → blocked by **coordination**
   (`foreign_active`) **and** **hygiene** (`blocks_edit` because the tree is
   dirty in scope). B should not edit.
3. Agent A calls `finish` with `changed_files` including `pkg/a.py` → passes
   declared-scope dirty acknowledgment. Finish fails on **live** foreign dirty overlap only
   (`foreign_active` / `foreign_stale`). **Queued** foreign peers do not
   appear in `foreign_dirty_overlaps`.
4. Resolution: coordinate (queue/promote/clear **active** foreign intent),
   stash/commit foreign WIP, or narrow scope — not kill foreign PIDs.

### Start / finish workflow transitions

Workflow `status` values are **not** persisted registry lifecycle states.

| Tool response                                 | `edit_allowed` | Agent action                                                                                                      |
|-----------------------------------------------|----------------|-------------------------------------------------------------------------------------------------------------------|
| `start` → `needs_analysis`                    | `false`        | `analyze_repository` → `start` again                                                                              |
| `start` → `queued`                            | `false`        | Wait → `promote`; re-analyze if `before_run_evicted`                                                              |
| `start` → `blocked`                           | `false`        | Follow `next_step` (`message` matches); do not edit unless `continue_own_wip` was requested and returned `active` |
| `start` → `active`                            | `true`         | Edit inside declared scope only; read `budget.gate_preview` as advisory                                           |
| `finish` → `accepted`                         | —              | Intent cleared (if receipt ok); no out-of-scope dirty in hygiene view                                             |
| `finish` → `accepted_with_external_changes`   | —              | Patch accepted; report `external_changes` — other paths dirty outside declared scope                              |
| `finish` → `unverified` / `workspace_hygiene` | —              | Fix `missing_evidence`, coordinate `foreign_dirty_overlap`, or (under `CODECLONE_STRICT_FINISH`) reconcile `own_unscoped_dirty` |
| `finish` → `violated`                         | —              | Fix regressions or widen scope via new `start`                                                                    |
| `finish` → `expired`                          | —              | Re-analyze → new `start` (digest mismatch)                                                                        |
