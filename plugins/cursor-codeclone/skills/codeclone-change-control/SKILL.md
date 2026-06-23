---
name: codeclone-change-control
description: MANDATORY HARD GATE when CodeClone MCP is connected. Before ANY repository file write, obtain edit_allowed=true from start_controlled_change. Before claiming done/verified/ready, finish_controlled_change must accept and clear the intent.
---

# CodeClone Change Control

**MANDATORY HARD GATE before ANY repository file write** when `start_controlled_change` / `finish_controlled_change` are available.

## Gate ON / OFF

**ON** — MCP workflow tools are visible and any tracked repository write is planned: code, tests, docs, config, schemas, or metadata.

**OFF** — read-only or analysis-only work with no repository writes.

`Implement`, `fix`, `refactor`, or a request to skip change control does **not** turn the gate off.

MCP unavailable and edits required → report **`BLOCKED`**. No CLI, local-report fallback, or silent edits.

## Hard prohibitions

1. No first edit until `start_controlled_change` returns `status:"active"` and `edit_allowed:true`, using an absolute `root`.
2. No completion claim until `finish_controlled_change` returns `accepted` or `accepted_with_external_changes`, `intent_cleared:true`, and `scope_check.status` is `clean` or `expanded`.
3. No silent scope expansion. Need another path → obtain a wider authorized scope before editing it.
4. No edit while `queued`, `blocked`, or `needs_analysis`; follow `next_step` or report **`BLOCKED`**.
5. Never touch `do_not_touch`. `review_context` and clone cohorts are context, not edit targets.
6. Never mix workflow `start` / `finish` with atomic verification in one cycle.
7. Findings and controller outcomes are authoritative; do not reinterpret or work around them.

`status:"active"` without `edit_allowed:true` is **not** permission.

## One cycle

```text
analyze_repository(root=<abs>)
→ [get_implementation_context]
→ start_controlled_change(root=<abs>, scope={...}, intent="...")
→ get_relevant_memory(root=<abs>, intent_id=...)
→ edit inside declared scope
→ analyze_repository(root=<abs>) when the derived profile requires it
→ [manage_engineering_memory(action="record_candidate", ...)]
→ finish_controlled_change(
      intent_id=...,
      changed_files=[...] XOR diff_ref=...,
      after_run_id=... when required,
  )
```

- Reuse a valid recent analysis for the same absolute `root`.
- Use Implementation Context before broad search or unclear scope; see `codeclone-implementation-context`.
- Bracketed steps are conditionally required, not decorative.

## Scope

| Field | Rule |
|-------|------|
| `allowed_files` | Primary implementation files and new modules |
| `allowed_related` | Ancillary tests, docs, fixtures, or helpers declared before editing |
| `forbidden` / `do_not_touch` | Hard boundary; baseline, cache, generated state, and `.codeclone/**` are not ordinary edit scope |

Touching declared `allowed_related` may produce `scope_check.status:"expanded"`. That does not permit undeclared edits.

To continue your own dirty WIP when blocked only by your declared overlap, use `dirty_scope_policy="continue_own_wip"` if supported by the returned recovery path.

## Verification profiles

The controller derives the profile; the agent does not choose or downgrade it.

- Python or governance changes may require a fresh after-run and `after_run_id`.
- Documentation-only or non-Python patches may verify from patch evidence.
- State-artifact changes are violations.

Use `help(topic="verification_profiles")` when the returned response requires clarification.

## Finish evidence

- Supply exactly one of `changed_files` or `diff_ref`.
- Supply `after_run_id` when `verification.after_run_required:true`.
- Include every path touched; finish reconciles against the full Git state.
- Record an Engineering Memory candidate only when the cycle produced a durable incident, decision, contradiction, risk, complexity finding, or reusable verification anchor.
- `propose_memory=true` may be used when supported; chat history is not Engineering Memory.

## Completion gate

Do not say `done`, `verified`, `implemented`, or `ready` unless all hold:

- finish status is `accepted` or `accepted_with_external_changes`;
- `intent_cleared:true`;
- `scope_check.status` is `clean` or `expanded`;
- warnings from `claims.valid:false` are reported.

Also report accepted advisories:

- `accepted_with_external_changes`;
- negative `verification.structural_delta.health_delta`;
- `verdict:"regressed"` or `"mixed"`.

Do not present such a patch as fully clean.

## Recovery

| Signal | Action |
|--------|--------|
| `needs_analysis` | Analyze the absolute root once, then retry |
| `queued` | Promote through `manage_change_intent`; no edit until active + allowed |
| `blocked` / failed MCP | Report **`BLOCKED`** and follow the exact `next_step` |
| `unverified` / `violated` | Keep the same `intent_id`; follow the exact `next_step` |
| Foreign in-scope overlap | Stop and coordinate; never kill a PID without explicit user confirmation |

A remaining active or recoverable own intent means the task is not complete.

## Atomic fallback

Only when workflow `start` / `finish` are unavailable and no workflow intent is active:

```text
get_blast_radius → edit → check_patch_contract(mode="verify") → create_review_receipt
```

Never mix atomic and workflow verification in one cycle.
