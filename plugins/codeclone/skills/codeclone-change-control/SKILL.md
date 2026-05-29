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
- For workflow tools, `start_controlled_change` performs workspace
  coordination. For atomic fallback, call
  `manage_change_intent(action="list_workspace", root=...)` before
  analysis when supported.
- If no valid recent run exists for the same absolute root, call
  `analyze_repository` before `start_controlled_change`.
- Declare intent before editing; in the primary workflow this means
  `start_controlled_change` must return `status: "active"` before edits.
- If the fix requires files outside declared scope, stop before editing
  them. Get user approval unless expansion was already explicitly
  allowed, then call `start_controlled_change` again with the expanded
  scope. Continue only when the expanded intent is active. Do not edit
  extra files based on blast-radius context alone.
- If concurrent workspace intents overlap your files, prefer
  `on_conflict="queue"` for follow-up work. Ask the user only when immediate
  editing is required or queue is not appropriate.
- Treat blast-radius dependents and clone cohorts as review context, not
  permission to modify.
- Treat `do_not_touch` as a boundary unless the user explicitly expands scope.
  Escalate to user only if the edit requires touching them.
- Treat `review_context` as context, not an edit ban.
- Do not update baselines, CodeClone state/cache, analysis cache, canonical
  reports, or generated state as part of a functional change.
- Do not fall back to CLI or local report files.
- CodeClone is the source of truth — do not reinterpret findings independently.
- Never auto-suppress findings or mutate CodeClone baseline state.
- Run routine controller steps automatically. Queue blocked follow-up work
  automatically — do not ask before queueing. Ask the user only when: scope
  expansion is needed and was not already explicitly allowed, a `do_not_touch`
  path must be touched, patch contract returned `violated` or returned
  `unverified` and the agent cannot execute the deterministic `next_step`, or
  baseline/CodeClone state/cache/generated state would be modified.

## Workflow

### Primary workflow

```
analyze_repository                                            # before-run
→ start_controlled_change(root=..., scope={...}, intent="...")
→ edit declared files
→ analyze_repository                                          # after-run (profile-dependent)
→ finish_controlled_change(intent_id=..., changed_files=[...], after_run_id=...)
```

Use this workflow when the connected MCP server supports
`start_controlled_change` and `finish_controlled_change`.

`start_controlled_change` returns workspace state, blast radius (direct
dependents, structural risk, do-not-touch, review context), and patch
budget in a single call. If `status: "needs_analysis"`, call
`analyze_repository` first.

`finish_controlled_change` handles scope check, patch verification,
claim validation, review receipt, and intent cleanup. If
`user_action_required: true`, stop and follow the `next_step` hint.

Workflow profiles determine which steps are needed:

- **Python structural / governance config**:
  `analyze` → `start` → edit → `analyze` → `finish(after_run_id=...)`
- **Documentation-only / non-Python**:
  `analyze` → `start` → edit → `finish(changed_files=[...])`
  For `non_python_patch`, report controller-stated limitations and do not
  present the result as full structural verification.

Do not mix workflow and atomic verification paths in the same edit
cycle. Queue/promote/recover via `manage_change_intent` is allowed.

### Queue/promote workflow

When `start_controlled_change` returns `status: "queued"`:

1. Do not edit until promoted.
2. Wait for the foreign intent to clear.
3. `manage_change_intent(action="promote", intent_id=...)`
   — edit only after promote returns `status: "active"`
   — if `before_run_evicted`: re-analyze and re-start

### Atomic workflow (fallback)

Use the atomic workflow only when `start_controlled_change` or
`finish_controlled_change` are unavailable, or for advanced operations
(queue management, recovery, step-by-step debugging):

```
manage_change_intent(action="list_workspace", root=...)
→ analyze_repository
→ manage_change_intent(action="declare")
→ get_blast_radius
→ check_patch_contract(mode="budget")
→ edit declared files
→ analyze_repository
→ manage_change_intent(action="check", intent_id=..., changed_files=[...])
→ check_patch_contract(mode="verify", after_run_id=..., intent_id=...)
→ validate_review_claims
→ create_review_receipt
→ manage_change_intent(action="clear")
```

Older MCP servers may not support `start_controlled_change`,
`finish_controlled_change`, `validate_review_claims`, or
`create_review_receipt`. Legacy-compatible steps may be skipped when
unavailable, and the summary must say so explicitly.

## Intent first

Before editing, call `start_controlled_change`. It declares the intent,
returns workspace coordination state, blast radius, and patch budget.

Declare scope includes:

- intended files (`allowed_files`)
- allowed related files (`allowed_related`)
- forbidden files (`forbidden`)
- short intent description
- expected structural effects

Example expected effects:

- no new clone group
- no new dead code
- no dependency cycle
- no baseline update

Use `manage_change_intent(action="declare")` only in the atomic fallback
workflow or when explicitly following a controller-provided recovery path.

## Scope expansion

If the fix requires a file outside declared scope:

1. stop;
2. explain why the extra file is needed;
3. get user approval unless the user already explicitly allowed expansion;
4. call `start_controlled_change` again with the expanded scope to get
   a fresh intent with updated blast radius and budget;
5. continue only after the expanded intent is active.

A patch that fixes the issue but expands scope silently is a failed patch.
Do not edit extra files based on blast-radius context alone.

## Blast radius

`start_controlled_change` returns blast radius context in its response:
direct dependents, clone cohort members, structural risk signals,
do-not-touch paths, and review context. When the radius is high, a
bounded transitive summary is also included.

Use a separate `get_blast_radius(depth="transitive")` call only when
the bounded summary is insufficient and you need the full transitive
dependency graph.

Read the blast radius response this way:

- `direct_dependents`: review before changing public behavior
- `clone_cohort_members`: comparison context, not automatic edit targets
- `structural_risk`: risk context for review priority
- `do_not_touch`: paths that require explicit approval; escalate to user
  only if the edit requires touching them
- `review_context`: supporting context, not a ban
- `transitive_summary`: downstream risk awareness (when present)

## Patch budget

Budget is included in the `start_controlled_change` response. Review that
budget before editing. Do not introduce new clone groups, dead code,
dependency cycles, API breaks, or baseline changes unless explicitly allowed.

Use `check_patch_contract(mode="budget")` only in the atomic fallback
workflow or for standalone planning, such as planning around a queued
intent. Budget on a queued intent is advisory and does not grant edit
permission.

## Patch verification

After editing, call `finish_controlled_change`:

```
finish_controlled_change(
    intent_id=...,
    changed_files=[...],              # or diff_ref=...
    after_run_id=...,                 # required for python_structural / governance_config
    review_text="...",                # optional, for claim validation
)
```

The tool handles: scope check, patch contract verification, claim
validation, review receipt generation, and intent cleanup.

Intent stays active on non-accepted results — retry `finish` on the
**same `intent_id`** after resolving the issue:

- `status: "unverified"` — follow `next_step` (e.g., run
  `analyze_repository`, then call `finish` again with `after_run_id`)
- `status: "violated"` (scope) — either remove out-of-scope changes and
  retry `finish`, or expand scope via `start_controlled_change`
- `user_action_required: true` — stop and escalate to the user

Do not start a new cycle unless the intent is expired or scope must
change. Do not claim the patch is verified on non-accepted status.

## Verification profiles

The controller derives a **verification profile** from actual changed files
during `finish_controlled_change` (through the underlying verify path), or
directly during `check_patch_contract(mode="verify")` in the atomic workflow.
The profile determines which structural checks apply. The agent does not
choose the profile.

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

In the primary workflow, pass `review_text` to `finish_controlled_change`
when you want final summary claims validated. If claim validation is
recommended and `review_text` is provided, `finish` runs claim validation
and returns the result.

Use `validate_review_claims` directly only in the atomic fallback workflow
or when re-validating changed review text after `finish`.

Do not claim:

- report-only signals are CI failures
- Security Surfaces are vulnerabilities
- known baseline debt is a new regression
- dead code exists where runtime reachability evidence says otherwise
- a fix is verified without an after-run and patch contract check

## Review receipt

In the primary workflow, `finish_controlled_change` creates the review
receipt when `create_receipt=true` (default). Do not call
`create_review_receipt` separately unless using the atomic fallback
workflow or manually regenerating a receipt.

The final user summary should include:

- declared scope
- scope expansion, if any
- blast radius summary
- patch contract status
- remaining human decisions
- receipt content, if returned in finish response

## Success criteria

The task is complete only when:

- `start_controlled_change` returned an active intent before editing;
  if queued, it was promoted before editing
- blast radius was inspected (included in start response)
- edits stayed inside declared scope, or expansion was explicit
- `finish_controlled_change` returned `status: "accepted"` or
  `"accepted_with_external_changes"`; `after_run_id` was provided when
  required by the verification profile
- `intent_cleared` is `true` in the finish response
- baseline, CodeClone state/cache, and generated reports were not changed
  accidentally
- if finish returned claims warnings, they were reported

## Non-goals

- Do not use this skill for quick hotspot snapshots; use `codeclone-hotspots`.
- Do not use this skill for passive structural review with no edits; use
  `codeclone-review`.
- Do not auto-fix unrelated findings.
- Do not turn report-only context into gates.
- Do not make baseline refresh part of a functional patch.
