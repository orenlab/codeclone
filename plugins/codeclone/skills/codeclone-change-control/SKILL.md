---
name: codeclone-change-control
description: Mandatory before any repository file edit when CodeClone MCP is connected — intent, scoped edit, verify, receipt, advisory reporting.
---

# CodeClone Change Control

Edit pipeline for the **target Python repository** (source, `tests/`, docs, config).
CodeClone MCP available → follow this pipeline. Coverage/CI/docs labels do **not**
skip intent. WIP needs a new intent each cycle.

**Skip pipeline** only when: no files will change; analysis-only; MCP unavailable
(edits → BLOCKED). Not for read-only review (`codeclone-review`) or snapshots
(`codeclone-hotspots`).

Findings are source of truth — do not reinterpret. No CLI/local-report fallback.
Never mutate baseline, cache, canonical reports, or generated state; never
auto-suppress. Pass absolute `root` to analysis tools.

Use CodeClone MCP tools via the plugin MCP config.

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
3. edit inside declared scope only
4. analyze_repository(root=abs)           # after-run ONLY if finish will require it
5. finish_controlled_change(...)          # see decision table — same intent_id
```

Keep `run_id`, `intent_id`, and the before-run from step 1 through the cycle.
Intent binds to the **before-run digest** — do not redeclare on the after-run.

### After `start` (`edit_allowed` gate)

| Response         | Action                                                                                                |
|------------------|-------------------------------------------------------------------------------------------------------|
| `needs_analysis` | Run step 1 for same `root`, then `start` again                                                        |
| `queued`         | **No edits.** Wait → `manage_change_intent(promote)`. If `before_run_evicted`: step 1 → `start` again |
| `active`         | Read `blast_radius` + `budget`. Edit only if `edit_allowed=true`                                      |

Before edit: scan `do_not_touch` (hard boundary), `direct_dependents`, clone
cohort / `review_context` (context only). `get_blast_radius(transitive)` only if
start summary is insufficient.

Declare in `start`: `allowed_files`, `allowed_related`, `forbidden`, `intent`,
`expected_effects`. Outside scope → stop → user OK (unless already allowed) →
new `start` with wider scope. Silent expansion = failed patch. Foreign overlap →
`on_conflict=queue` unless immediate edit required.

### After edit → `finish`

Evidence: **`changed_files` XOR `diff_ref`** — exactly one; both or neither is
an error. `before_run_id` is resolved from the intent — do not pass a new declare.

```
finish_controlled_change(
  intent_id=...,
  changed_files=[...] | diff_ref=...,     # XOR
  after_run_id=...,                       # when verification.after_run_required
  review_text=...,                        # optional; validated if recommended
)
```

Internal order (do not replicate manually): scope **check** → **verify** → claims
(if `review_text` + `claim_validation_recommended`) → receipt → clear.

### After `finish`

| Status                                        | Action                                                                                                 |
|-----------------------------------------------|--------------------------------------------------------------------------------------------------------|
| `accepted` / `accepted_with_external_changes` | Cycle complete only if `intent_cleared=true` **and** §Completion gate + §Advisory acceptance satisfied |
| `unverified`                                  | Intent stays active. Follow `next_step` (usually after-run), then **retry same `intent_id`**           |
| `violated` (scope)                            | Fix files or expand scope via new `start`; retry same `intent_id`                                      |
| `expired`                                     | Before-run digest stale. Re-analyze → new `start`                                                      |
| `user_action_required=true`                   | Stop; follow `next_step` or escalate                                                                   |

Do not start a new intent unless scope changed or intent expired.

## Completion gate

No "done" / "verified" / "implemented" / "ready" unless all hold:

- `finish.status` is `accepted` or `accepted_with_external_changes`
- `intent_cleared=true`
- claim warnings reported when `claims.valid` is false
- §Advisory acceptance signals reported when present

`accepted` = patch contract passed for declared scope — **not** "no regressions" or
unchanged health.

## Advisory acceptance (do not hide)

Read **before** the user summary, even when `intent_cleared=true`:

| Field                                        | Report when                            |
|----------------------------------------------|----------------------------------------|
| `verification.structural_delta.health_delta` | `< 0` — health dropped; cite delta     |
| `verification.structural_delta.verdict`      | `regressed` or `mixed`                 |
| `external_regressions`, `gate_worsened`      | non-empty / true                       |
| `accepted_with_external_changes`             | name external workspace signal         |
| `contract_violations`                        | non-empty (`relaxed` may still accept) |
| `receipt.verdict`, `human_decision_points`   | `needs_attention` or non-empty         |

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
→ validate_review_claims → create_review_receipt → clear
```

Say explicitly which tools were skipped. Never mix with normal pipeline in one cycle.

## Escalate to user

Scope expansion; touch `do_not_touch`; foreign active without queue; blocked
`next_step`; baseline/cache/report mutation; recover foreign intent. Routine
analyze/queue/promote runs automatically.

## Claims (do not)

Report-only ≠ CI fail; Security Surfaces ≠ vulns; baselined debt ≠ new regression;
dead code vs runtime reachability; structural verify without profile evidence.
