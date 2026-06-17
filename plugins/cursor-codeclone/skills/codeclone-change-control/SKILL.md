---
name: codeclone-change-control
description: MANDATORY HARD GATE before ANY repository file write when CodeClone MCP is connected — start_controlled_change before the first edit, finish_controlled_change (accepted) before claiming done.
---

# CodeClone Change Control — MANDATORY GATE

Not advisory. Applies before ANY write to a tracked repository file (code, tests,
docs, config) whenever CodeClone MCP is connected. No exceptions, no rationalizing
a skipped step.

## The loop (do not skip, reorder, or approximate)

1. `analyze_repository(root=<abs>)` — skip only if a valid recent run for the same absolute root exists.
2. `start_controlled_change(root=<abs>, scope={allowed_files:[...]}, intent="...")` — returns blast radius, budget,
   `edit_allowed`, `intent_id`.
3. `get_relevant_memory(root=<abs>, intent_id=...)` — REQUIRED after `edit_allowed:true`. `root` is mandatory. Read
   contract / stale / contradiction alerts.
4. Edit — inside declared scope ONLY.
5. `analyze_repository(root=<abs>)` — after-run; required for any `.py` or governance-config change.
6. Engineering Memory `record_candidate` — if the cycle had any incident / complexity / decision (see
   `codeclone-engineering-memory`). Chat is NOT memory.
7. `finish_controlled_change(intent_id=..., changed_files=[...], after_run_id=...)`.

## Hard rules — MUST / MUST NOT

- MUST NOT edit before `start` returned `status:"active"` AND `edit_allowed:true`.
- MUST NOT touch a file outside `scope.allowed_files`. Need one → `start` again with a wider scope FIRST. Never widen
  silently or "just this once".
- MUST NOT touch `do_not_touch` paths (baseline, `.codeclone/**`, cache, generated). `review_context` is context, not a
  ban.
- `status:"queued"` → DO NOT edit; `manage_change_intent(action="promote")` first, edit only after it returns `active`.
- `finish` `status:"unverified"`/`"violated"` → intent stays active; follow the exact `next_step`. Do not invent a
  recovery; do not switch to atomic verify.
- Live foreign intent overlap → STOP. Never kill a PID without explicit user confirmation it is abandoned.
- Findings are the source of truth. Do not reinterpret, soften, or engineer around the gate.

## Completion gate — do not say "done / verified / ready" unless ALL hold

- `finish` returned `accepted` (or `accepted_with_external_changes`).
- `scope_check.status` = `clean` or `expanded`.
- `intent_cleared: true`.
- If `claims.valid: false` → report the warnings, do not suppress.

Otherwise report `BLOCKED` / `UNVERIFIED` with the `intent_id` and the exact missing
step. A leftover active or recoverable own intent is a blocked task, not a finished
one. `accepted_with_external_changes` → report the external-change advisory; do not
present the patch as fully clean.

## Reading the response

> Key / easily-misread fields; the real response carries more.

| Field                                  | Meaning                                                                                 |
|----------------------------------------|-----------------------------------------------------------------------------------------|
| `edit_allowed`                         | true only when intent active AND hygiene clear — authorization lives HERE, nowhere else |
| `scope.allowed_files` / `do_not_touch` | your hard edit boundary / paths needing separate approval                               |
| `blast_radius.radius_level`            | low / medium / high — context, NOT permission to widen scope                            |
| `finish.scope_check.status`            | clean / expanded / violated (out-of-scope file touched)                                 |
| `finish.verification.status`           | accepted / unverified (missing evidence) / violated (regression)                        |
| `finish_block_reason`                  | missing_evidence / foreign_dirty_overlap / own_unscoped_dirty (strict only)             |
| `intent_cleared`                       | false = intent still open = NOT done                                                    |

## Verification profiles (controller derives — you do not choose)

`python_structural` (any `.py` touched) → needs an after-run + `after_run_id`.
`governance_config` → after-run, no structural checks. `documentation_only` /
`non_python_patch` → verify from `changed_files`, no after-run. `state_artifact_change`
(baseline / cache / generated) → violated.

## Atomic fallback

Only when `start`/`finish` are unavailable: `get_blast_radius` → edit →
`check_patch_contract(mode="verify")` → `create_review_receipt`. Never mix atomic and
workflow verification in one cycle. Queue / promote / recover always go through
`manage_change_intent`.

Skip the whole gate only for read-only / analysis tasks, or when CodeClone MCP is
unavailable AND the task is read-only (then stop and report blockers for any edit).
