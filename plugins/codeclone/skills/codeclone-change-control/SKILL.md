---
name: codeclone-change-control
description: Use when Codex should modify a Python repository through CodeClone MCP — intent-first change workflow, blast radius, scoped edits, patch verification, and review receipt.
---

# CodeClone Change Control

Use this skill when the task requires changing files in a Python repository with
CodeClone MCP available.

This is not a passive review workflow. CodeClone starts before a diff exists:
declare intent, inspect structural risk, edit inside scope, then verify the
patch.

## Activation contract

Use this workflow whenever this skill is selected for a repository edit. Start
with a pre-edit MCP run and keep the returned `run_id` and `intent_id` for
verification. If a required MCP tool is unavailable in the connected server,
continue with the available steps and state which step was skipped.

Do not downgrade the task to an ordinary edit after this skill has been
selected. The only valid reasons to skip the workflow are: no repository files
will be changed, CodeClone MCP is unavailable, or the user explicitly asks for
analysis only.

## Rules

- Use MCP tools only when invoked through the CodeClone plugin.
- If no latest MCP run exists, call `analyze_repository` yourself before
  declaring intent.
- Declare intent before editing.
- Do not silently expand scope.
- Treat blast-radius dependents and clone cohorts as review context, not
  permission to modify.
- Treat `do_not_touch` as a boundary unless the user explicitly expands scope.
- Treat `review_context` as context, not an edit ban.
- Do not update baselines, cache, or generated reports as part of a functional
  change.
- Do not fall back to CLI or local report files.
- CodeClone is the source of truth — do not reinterpret findings independently.
- Never auto-suppress findings or mutate CodeClone baseline state.

## Workflow

```
analyze_repository
→ manage_change_intent(action="declare")
→ get_blast_radius
→ check_patch_contract(mode="budget")
→ edit code
→ analyze_repository
→ manage_change_intent(action="check")
→ check_patch_contract(mode="verify")
→ validate_review_claims
→ create_review_receipt
```

Use the full path for normal code changes. Skip only steps that are unavailable
in the connected CodeClone MCP server.
Keep the pre-edit `run_id` as `before_run_id`; verify against the explicit
after-run produced after the edit.

## Intent first

Before editing, call:

```
manage_change_intent(action="declare")
```

Declare:

- intended files
- allowed related files
- forbidden files
- short intent
- expected effects

Example expected effects:

- no new clone group
- no new dead code
- no dependency cycle
- no baseline update

## Scope expansion

If the fix requires a file outside declared scope:

1. stop;
2. explain why the extra file is needed;
3. redeclare intent with the expanded scope;
4. continue only after the new intent is active.

A patch that fixes the issue but expands scope silently is a failed patch.

## Blast radius

Use:

```
get_blast_radius
```

Read the response this way:

- `direct_dependents` / `transitive_dependents`: review before changing public
  behavior
- `clone_cohort_members`: comparison context, not automatic edit targets
- `structural_risk`: risk context for review priority
- `do_not_touch`: paths that require explicit approval or a separate workflow
- `review_context`: supporting context, not a ban

## Patch budget

Before editing, call:

```
check_patch_contract(mode="budget")
```

Use the returned budget as the edit boundary. Do not introduce new clone groups,
dead code, dependency cycles, API breaks, or baseline changes unless explicitly
allowed.

## Patch verification

After editing, run analysis again, then call:

```
manage_change_intent(action="check")
check_patch_contract(mode="verify")
```

If the result is `unverified`, report what is missing. Do not claim the patch is
verified.

If the result is `violated`, stop and explain the violation instead of continuing
to broaden the patch.

## Claim discipline

When writing a summary, call:

```
validate_review_claims
```

Do not claim:

- report-only signals are CI failures
- Security Surfaces are vulnerabilities
- known baseline debt is a new regression
- dead code exists where runtime reachability evidence says otherwise
- a fix is verified without an after-run and patch contract check

## Review receipt

At the end, call:

```
create_review_receipt
```

The final user summary should include:

- declared scope
- scope expansion, if any
- blast radius summary
- patch contract status
- remaining human decisions
- receipt location or payload, if returned

## Success criteria

The task is complete only when:

- intent was declared before editing
- blast radius was inspected
- edits stayed inside declared scope, or expansion was explicit
- patch contract was checked
- baseline/cache/generated state was not changed accidentally
- claims were validated when a review summary was written
- a review receipt was created when available

## Non-goals

- Do not use this skill for quick hotspot snapshots; use `codeclone-hotspots`.
- Do not use this skill for passive structural review with no edits; use
  `codeclone-review`.
- Do not auto-fix unrelated findings.
- Do not turn report-only context into gates.
- Do not make baseline refresh part of a functional patch.
