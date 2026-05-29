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
with a workspace intent check, then run pre-edit analysis and keep the returned
`run_id` and `intent_id` for verification. If a required MCP tool is
unavailable, continue only for read-only analysis. For repository edits that
require change control, stop and report the blocker unless the unavailable tool
is explicitly optional or legacy-compatible.

Do not downgrade the task to an ordinary edit after this skill has been
selected. The only valid reasons to skip the workflow are: no repository files
will be changed, the user explicitly asks for analysis only, or CodeClone MCP
is unavailable and the task remains read-only. Do not perform repository edits
without change control after this skill is selected.

## Rules

- Use MCP tools only when invoked through the CodeClone plugin.
- Call `manage_change_intent(action="list_workspace", root=...)` before
  analysis when the connected server supports it.
- If no latest MCP run exists after the workspace check, call
  `analyze_repository` yourself before declaring intent.
- Declare intent before editing.
- Do not silently expand scope.
- If concurrent workspace intents overlap your files, prefer
  `on_conflict="queue"` for follow-up work. Ask the user only when immediate
  editing is required or queue is not appropriate.
- Treat blast-radius dependents and clone cohorts as review context, not
  permission to modify.
- Treat `do_not_touch` as a boundary unless the user explicitly expands scope.
- Treat `review_context` as context, not an edit ban.
- Do not update baselines, analysis cache, or generated reports as part of a
  functional change.
- Do not fall back to CLI or local report files.
- CodeClone is the source of truth — do not reinterpret findings independently.
- Never auto-suppress findings or mutate CodeClone baseline state.
- Run routine controller steps automatically. Queue blocked follow-up work
  automatically — do not ask before queueing. Ask the user only when: scope
  expansion is needed, a `do_not_touch` path must be touched, patch contract
  returned `violated` or `unverified`, or baseline/cache/generated state would
  be modified.

## Workflow

```
manage_change_intent(action="list_workspace", root=...)
→ analyze_repository                                        # before-run
→ manage_change_intent(action="declare")                    # intent bound to before-run
→ get_blast_radius
→ check_patch_contract(mode="budget")
→ edit declared files
→ analyze_repository                                        # after-run (skip for docs-only)
→ manage_change_intent(action="check", intent_id=..., changed_files=[...])
→ check_patch_contract(mode="verify", after_run_id=..., intent_id=...)  # before_run_id auto-resolved
→ validate_review_claims                                    # skip only if claim_validation_recommended is explicitly false
→ create_review_receipt
→ manage_change_intent(action="clear")
```

The intent stays bound to the before-run. After re-analyze, pass `intent_id`
explicitly to `check` and `verify`; without it, `_resolve_intent` resolves by
latest run id and misses the intent. Do not redeclare on the after-run:
`verify` compares the intent's `report_digest` against the before-run, and a
redeclared intent would cause an `expired` mismatch. Use `diff_ref=...` instead
of `changed_files=[...]` when the changed set should come from git.

Older MCP servers may not support `list_workspace`, `validate_review_claims`,
or `create_review_receipt`. These legacy-compatible steps may be skipped when
unavailable, and the summary must say so explicitly. Do not skip core edit
control steps: `analyze_repository`, `declare`, `check`, and `verify`. Keep
the pre-edit `run_id` as `before_run_id`; verify against the explicit
after-run produced after the edit.

## Workspace check

Before analysis, call:

```
manage_change_intent(action="list_workspace", root="/absolute/repo")
```

If it returns active intents from other agents, compare their `scope` to your
planned files. A hard overlap means another agent claimed the same primary file.
A soft overlap means your primary file is in another agent's related context, or
the reverse.

Do not ask the user before queueing blocked follow-up work that can wait.
Prefer `on_conflict="queue"` in the declare step to queue behind the foreign
intent. Ask the user only if immediate editing is required, recovery/reset is
needed, or a `do_not_touch` path must be touched:

```
manage_change_intent(action="declare", scope={...}, on_conflict="queue")
```

A queued intent does not own scope, does not pin the before-run, and cannot pass
verification. You may call `check_patch_contract(mode="budget")` on a queued
intent for planning, but it returns `edit_allowed=false`. When the foreign
intent clears, promote it:

```
manage_change_intent(action="promote", intent_id=...)
```

If promote returns `status="queued"` with `blocking_count`, the foreign intent is
still active — wait and retry. If it returns `reason="before_run_evicted"`,
re-analyze and redeclare the intent.

## Legacy workflow

Use this only when `list_workspace` is unavailable in the connected MCP server:

```
analyze_repository
→ manage_change_intent(action="declare")
→ get_blast_radius
→ check_patch_contract(mode="budget")
→ edit declared files
→ analyze_repository
→ manage_change_intent(action="check", intent_id=..., changed_files=[...])
→ check_patch_contract(mode="verify", before_run_id=..., after_run_id=..., intent_id=...)
→ validate_review_claims
→ create_review_receipt
→ manage_change_intent(action="clear")                      # if supported
```

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

After editing, run analysis again, then pass the original `intent_id`
explicitly:

```
manage_change_intent(action="check", intent_id=..., changed_files=[...])
check_patch_contract(mode="verify", intent_id=..., after_run_id=...)
```

`before_run_id` auto-resolves from the intent record when `intent_id` is
provided. `after_run_id` is required only for `python_structural` and
`governance_config` profiles. For `documentation_only` and `non_python_patch`,
pass `changed_files` or `diff_ref` evidence and omit `after_run_id`.

Use `diff_ref=...` instead of `changed_files=[...]` when the changed set should
come from git.

If the result is `unverified` or `violated`, read the `next_step` hint and
follow it. Do not claim the patch is verified. Do not invent a different
recovery path — the hint is deterministic and authoritative.

If `claim_validation_recommended` is `true`, call `validate_review_claims`
before writing a summary. If it is explicitly `false`, skip claim validation.

## Verification profiles

The controller derives a **verification profile** from actual changed files
during `check_patch_contract(mode="verify")`. The profile determines which
structural checks apply. The agent does not choose the profile.

| Profile                 | When                          | `after_run` required | Structural checks |
|-------------------------|-------------------------------|----------------------|-------------------|
| `python_structural`     | any `.py` / `.pyi` touched    | yes                  | all               |
| `governance_config`     | config files only             | yes                  | not applicable    |
| `documentation_only`    | only docs files               | no                   | not applicable    |
| `non_python_patch`      | other files, no Python / docs | no                   | not applicable    |
| `state_artifact_change` | baseline or CodeClone state/cache touched | no (violated) | not applicable |

Rules:

- If any Python source, governance config, baseline, CodeClone state/cache, or generated state
  was touched, the lightweight path is not accepted.
- Documentation-only patches can verify without `after_run_id` when
  `changed_files` or `diff_ref` evidence is provided.
- Other non-Python patches may verify without `after_run_id`, but only with
  controller-reported limitations. Do not present this as full structural
  verification.
- Do not claim which profile applies — CodeClone decides.
- Receipts use "not applicable" for skipped structural checks, never "passed".
- Claim Guard may reject or warn on claims that exceed the derived profile.
  For documentation-only patches, "no Python files touched" is allowed;
  "no structural regressions" requires structural evidence from an after-run.

## Claim discipline

When writing a summary and `claim_validation_recommended` was `true`, call:

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

- intent was declared before editing; if queued, it was promoted before editing
- blast radius was inspected
- edits stayed inside declared scope, or expansion was explicit
- patch contract was checked: either an after-run was created (Python
  structural, governance config) or verify derived a profile that does not
  require it (documentation-only, non-Python)
- baseline/cache/generated state was not changed accidentally
- claims were validated when `claim_validation_recommended` was explicitly
  `true` in the controller response, not skipped by agent judgment
- a review receipt was created when the server supports it; if unsupported,
  the final summary states that receipt creation was unavailable

## Non-goals

- Do not use this skill for quick hotspot snapshots; use `codeclone-hotspots`.
- Do not use this skill for passive structural review with no edits; use
  `codeclone-review`.
- Do not auto-fix unrelated findings.
- Do not turn report-only context into gates.
- Do not make baseline refresh part of a functional patch.
