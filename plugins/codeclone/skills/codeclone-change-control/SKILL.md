---
name: codeclone-change-control
description: MANDATORY HARD GATE before ANY repository file write when CodeClone MCP is connected — read on every implement/fix/refactor task; start_controlled_change before first edit; finish_controlled_change before claiming done; see always-on rule change-control-gate.
---

# CodeClone Change Control

Edit pipeline for the **target Python repository** (source, `tests/`, docs, config).
CodeClone MCP available → follow this pipeline. Coverage/CI/docs labels do **not**
skip intent. Use `dirty_scope_policy="continue_own_wip"` only to resume known
uncommitted WIP in declared scope when start would otherwise block on dirty scope
alone — finish still proves scope via `changed_files` or `diff_ref`.

**Skip pipeline** only when: no files will change; analysis-only; MCP unavailable
(edits → BLOCKED). Not for read-only review (`codeclone-review`) or snapshots
(`codeclone-hotspots`).

Findings are source of truth — do not reinterpret. No CLI/local-report fallback.
Never mutate baseline, cache, canonical reports, or generated state; never
auto-suppress. Pass absolute `root` to analysis tools.

## Tool tiers

| Tier               | Tools                                                                                         | Role                             |
|--------------------|-----------------------------------------------------------------------------------------------|----------------------------------|
| **Normal**         | `analyze_repository`, `start_controlled_change`, `finish_controlled_change`                   | Every edit cycle — use these     |
| **Queue/recovery** | `manage_change_intent` (promote, recover, renew, reset)                                       | Multi-agent wait, crash recovery |
| **Advanced**       | `get_blast_radius`, `check_patch_contract`, `validate_review_claims`, `create_review_receipt` | Debugging or legacy servers only |

Workflow tools orchestrate the same steps as atomic tools. They **never run
analysis**. Do not call atomic verify/receipt/clear in the same cycle when
start/finish are available.

## Normal pipeline

One edit cycle:

```
1. analyze_repository(root=abs)           # before-run; skip if valid recent run
2. start_controlled_change(...)           # see decision table — before first edit
3. get_relevant_memory(root=abs, scope=... or intent_id=...)  # root required
4. edit inside declared scope only
5. analyze_repository(root=abs)           # after-run ONLY if finish will require it
6. record engineering memory (MCP)        # REQUIRED before finish if §Incident memory
7. finish_controlled_change(...)          # see decision table — same intent_id
   # optional: propose_memory=true on accept for draft memory candidates
```

Keep `run_id`, `intent_id`, and the before-run from step 1 through the cycle.
Intent binds to the **before-run digest** — do not redeclare on the after-run.

### Engineering Memory (step 3)

After `edit_allowed=true`, call `get_relevant_memory` before the first edit.
**Always pass absolute `root`** (same as `analyze_repository`); `intent_id` or
`scope` alone fails MCP validation. Requires `analyze_repository` before memory
reads. Default policy auto-bootstraps on `get_relevant_memory`; use
`refresh_from_run` for explicit ingest.

| Need                 | Tool                                                                     |
|----------------------|--------------------------------------------------------------------------|
| Ranked scope context | `get_relevant_memory(root=abs, scope=… \| intent_id=…)`                  |
| One path             | `query_engineering_memory(mode=for_path, path=…)`                        |
| Keyword search       | `query_engineering_memory(mode=search, query=…, filters={match_mode:…})`; optional `semantic=true` when index built |
| Draft observation    | `manage_engineering_memory(action=record_candidate, …)`                  |
| Post-edit proposals  | `finish(..., propose_memory=true)`                                       |

Full playbook: `codeclone-engineering-memory` skill and
`docs/book/26-engineering-memory.md`. Human approval via VS Code Memory view (not
MCP) required to promote
drafts — agents cannot activate records via MCP.

Do not use memory to expand scope, override findings, or justify `do_not_touch`
edits. Surface `contradiction_note` and stale warnings to the user.

### Incident memory (before step 7)

**Chat does not persist.** If the cycle had an incident, non-trivial complexity, or
a decision the next agent should not rediscover, call
`manage_engineering_memory(action=record_candidate, …)` **before**
`finish_controlled_change` — or use `propose_memory=true` on finish for a batch.

| Write when | Examples |
|------------|----------|
| Incident | verify/hygiene surprise, recovery, workaround, blocked then unblocked |
| Complexity | non-obvious root cause, multi-file debug, acted on stale/contradiction |
| Decision | tradeoff, “do not repeat X”, integration quirk |

Skip for trivial one-liner fixes only. See `change-control-gate` rule and
`codeclone-engineering-memory` skill.

Before `record_candidate`, compress to one durable fact with `subject_path` set;
target ≤300 chars (hard reject above `max_statement_chars`, default 1000).

### After `start` (`edit_allowed` gate)

| Response         | Action                                                                                                                                                                                                                       |
|------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `needs_analysis` | Run step 1 for same `root`, then `start` again                                                                                                                                                                               |
| `queued`         | **No edits.** Wait → `manage_change_intent(promote)`. If `before_run_evicted`: step 1 → `start` again                                                                                                                        |
| `blocked`        | **No edits.** Intent exists — clear via `manage_change_intent(clear)` if abandoning; follow `next_step`. If dirty scope is known WIP with no foreign overlap, retry `start` with `dirty_scope_policy="continue_own_wip"`. |
| `active`         | Read `blast_radius` + `budget`. Edit only if `edit_allowed=true`. Budget `gate_preview.would_fail` is advisory — edit may proceed, but verify may reject.                                                                    |

**Edit permission:** `status == "active"` alone is not enough — require
`edit_allowed == true`. Treat unknown start statuses as no permission.

Three independent contours (do not collapse):

```text
status     = persisted registry lifecycle
ownership  = runtime view (PID / TTL / lease)
hygiene    = git working tree ∩ declared scope
permission = edit_allowed (with status gate)
```

Before edit: scan `do_not_touch` (hard boundary), `direct_dependents`, clone
cohort / `review_context` (context only). `get_blast_radius(transitive)` only if
start summary is insufficient.

Declare in `start`: `allowed_files`, `allowed_related`, `forbidden`, `intent`,
`expected_effects`. Outside scope → stop → user OK (unless already allowed) →
new `start` with wider scope. Silent expansion = failed patch. Foreign overlap →
`on_conflict=queue` unless immediate edit required.

**Scope declaration rules:**

| Path kind                         | Declare in        | Notes                                                                         |
|-----------------------------------|-------------------|-------------------------------------------------------------------------------|
| Files you create or edit          | `allowed_files`   | **New modules go here**, not only `allowed_related`                           |
| Tests/docs/helpers you will touch | `allowed_related` | Finish-allowed; may show `scope: expanded`                                    |
| Paths you will not touch          | omit              | Foreign **active/stale** dirty paths outside your scope are ignored at finish |

### After edit → `finish`

Evidence: **`changed_files` XOR `diff_ref`** — exactly one; both or neither is
an error. `before_run_id` is resolved from the intent — do not pass a new declare.

**Git reconciliation (automatic):** finish cross-checks agent evidence against
the **full git working tree** and the dirty snapshot captured at `start` — not
honor-system. List every path you touched in `changed_files` when possible; the
controller also reads git and blocks under-reporting or silent out-of-scope
edits. You **must** declare scope wide enough at `start`.

| `finish_block_reason` | Meaning | Agent action |
|---|---|---|
| `missing_evidence` | Git dirty inside `allowed_files` / `allowed_related` but missing from evidence | Add paths to `changed_files` / `diff_ref` or revert |
| `new_unattributed_unscoped_dirty` | Out-of-scope dirty path appeared after `start` and is not foreign-attributed | Redeclare wider scope or revert |
| `modified_unattributed_unscoped_dirty` | Out-of-scope dirty path existed at `start` but changed after `start` and is not foreign-attributed | Redeclare wider scope or reconcile |
| `unknown_unattributed_unscoped_dirty` | Out-of-scope dirty path cannot be compared to a start snapshot; legacy/missing snapshot is conservative | Reconcile tree, restart with fresh intent, or redeclare |
| `foreign_dirty_overlap` | Foreign **active/stale** intent previously declared same in-scope path | Coordinate with user |

- Dirty paths outside your scope owned by a **foreign active/stale** intent →
  listed in `foreign_attributed_outside_scope`, **does not block** your finish.
- Dirty paths outside your scope that were already dirty at `start` and did not
  change are listed in `preexisting_unscoped_dirty`, **does not block** your
  finish.
- **`recoverable`** intents (dead owning PID) do **not** grant foreign
  attribution — their dirty paths count as normal workspace dirt unless you
  declare scope or revert.
- Legacy `own_unscoped_dirty` may appear as a compatibility alias for
  unattributed blocking dirt. Treat it as **unattributed**, not proof that the
  current agent owns the edit.
- On hygiene pass, scope check may use `files_for_scope_check` (evidence ∪
  unattributed blocking dirt) instead of evidence alone.

```
finish_controlled_change(
  intent_id=...,
  changed_files=[...] | diff_ref=...,     # XOR
  after_run_id=...,                       # when verification.after_run_required
  claims_text=...,                        # optional; validated when recommended
  review_text=...,                        # optional human note; not claim-validated
)
```

Internal order (do not replicate manually): hygiene **gate** → scope **check** →
**verify** → claims (if `claims_text` + `claim_validation_recommended`) → receipt
→ clear.

### After `finish`

| Status                                        | Action                                                                                                                            |
|-----------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `accepted` / `accepted_with_external_changes` | Cycle complete only if `intent_cleared=true` **and** §Completion gate + §Advisory acceptance satisfied                            |
| `unverified`                                  | Intent stays active. Follow `next_step` (usually after-run), then **retry same `intent_id`**                                      |
| `violated` (scope)                            | Fix files or expand scope via new `start`; retry same `intent_id`                                                                 |
| `expired`                                     | Before-run digest stale. Re-analyze → new `start`                                                                                 |
| `reason=workspace_hygiene`                    | **No atomic verify bypass.** Reconcile dirty scope/evidence → retry same `intent_id`. Queued foreign intents do not block finish. |
| `user_action_required=true`                   | Stop; follow `next_step` or escalate                                                                                              |

Do not start a new intent unless scope changed or intent expired.

## Completion gate

No "done" / "verified" / "implemented" / "ready" unless all hold:

- `finish.status` is `accepted` or `accepted_with_external_changes`
- `intent_cleared=true`
- claim warnings reported when `claims.valid` is false
- §Advisory acceptance signals reported when present

`accepted` = patch contract passed for declared scope — **not** "no regressions" or
unchanged health.

`novelty="known"` is baseline-relative, not patch-relative. It means the finding
fingerprint is accepted by the trusted baseline; it does **not** prove the patch
did not introduce or reintroduce it. Patch-local regression claims require clean
before-run to after-run evidence from compare/verify.

## Advisory acceptance (do not hide)

Read **before** the user summary, even when `intent_cleared=true`:

| Field                                        | Report when                                                    |
|----------------------------------------------|----------------------------------------------------------------|
| `verification.structural_delta.health_delta` | `< 0` — health dropped; cite delta even when verify `accepted` |
| `health_regression_advisory`                 | present on accepted finish when delta negative                 |
| `verification.reason: after_run_not_new`     | after-run equals before-run — re-analyze with new run_id       |
| `verification.structural_delta.verdict`      | `regressed` or `mixed`                                         |
| `external_regressions`, `gate_worsened`      | non-empty / true                                               |
| `accepted_with_external_changes`             | name external workspace signal                                 |
| `contract_violations`                        | non-empty (`relaxed` may still accept)                         |
| `receipt.verdict`, `human_decision_points`   | `needs_attention` or non-empty                                 |

**Anti-pattern:** `status: accepted` → skip reporting health drop or structural
regressions. Contract acceptance clears the intent; structural delta is
user-facing advisory.

**Example:** docs-only patch → `accepted`, `intent_cleared=true`, but
`health_delta: -2`, `verdict: regressed` → tell the user health fell; do not stop
at "patch accepted".

## Verify profiles (controller decides)

**`start` always required.** Profile affects after-run and structural checks only.

| Priority | Profile                 | Trigger                         | After-run |
|----------|-------------------------|---------------------------------|-----------|
| 1        | `state_artifact_change` | baseline/cache touched          | violated  |
| 2        | `python_structural`     | any `.py`/`.pyi` incl. tests    | yes       |
| 3        | `governance_config`     | pyproject, CI, Dockerfile… only | yes       |
| 4        | `documentation_only`    | docs only                       | no        |
| 5        | `non_python_patch`      | other non-py, non-docs          | no        |

Read `verification.verification_profile` and `after_run_required` from `finish` —
do not guess. Docs/non-python may verify without after-run when diff evidence
exists. Receipts: skipped checks = "not applicable", never "passed".

## Atomic fallback (legacy / debug only)

When start/finish unavailable:

```
list_workspace → analyze → declare → budget → edit → analyze → check → verify
→ validate_review_claims(text=..., patch_health_delta=verify.structural_delta.health_delta)
→ create_review_receipt → clear
```

Say explicitly which tools were skipped. Never mix with normal pipeline in one cycle.

## Escalate to user

Scope expansion; touch `do_not_touch`; foreign active without queue; blocked
`next_step`; baseline/cache/report mutation; recover foreign intent. Routine
analyze/queue/promote runs automatically.

## Claims (do not)

Report-only ≠ CI fail; Security Surfaces ≠ vulns; baselined debt ≠ new relative
to baseline; patch-local regression needs before/after evidence; dead code vs
runtime reachability; structural verify without profile evidence.
