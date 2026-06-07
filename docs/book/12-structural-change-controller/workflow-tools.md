## Pre-Change Workflow

1. Call `manage_change_intent(action="list_workspace", root="/abs/repo")` to
   see active intents from other agents before analysis.
   If it returns `ownership="recoverable"` for a matching run, use
   `manage_change_intent(action="recover")` instead of killing another MCP
   process or redeclaring blindly.
2. Run `analyze_repository` or `analyze_changed_paths`.
3. Declare scope with `manage_change_intent(action="declare")`.
4. If `concurrent_intents` is non-empty, narrow scope or coordinate before
   editing.
5. Inspect the returned `blast_radius_summary`.
6. Optionally call `get_blast_radius` for full dependent/context detail.
7. Call `check_patch_contract(mode="budget")` to inspect the active regression
   budget and metric headroom before editing.
8. Run analysis again after editing (produces the after-run).
9. Call `manage_change_intent(action="check", intent_id=..., changed_files=...)`
   with the original `intent_id`. Use `diff_ref=...` instead of
   `changed_files=...` when the changed set should come from git. The intent
   stays bound to the before-run; `verify` compares its `report_digest` against
   the before-run, so redeclaring on the after-run would cause an `expired`
   mismatch.
10. Call `check_patch_contract(mode="verify", before_run_id=...,
    after_run_id=..., intent_id=...)`.
11. Call `validate_review_claims` before publishing claim text in the atomic
    workflow, or pass `claims_text` to `finish_controlled_change`.
12. Call `create_review_receipt` to collect provenance, scope, blast radius,
    reviewed findings, patch status, human decision points, and claims-not-made.
13. Call `manage_change_intent(action="clear")` when the edit is complete.

`manage_change_intent` can return `clean`, `expanded`, `violated`, or
`expired`. Expiry means the report digest changed since declaration.

`check_patch_contract` never runs analysis itself. Budget mode reads one stored
run and optional intent. Verify mode compares explicit before/after stored runs,
previews gates, validates scope when intent is available, and reports baseline
abuse signals. Missing before or after runs return `status="unverified"` with
`reason="no_before_run"` or `reason="no_after_run"`.

Patch verify is run-relative, not baseline-novelty-relative: if a finding is
absent from the clean before-run and present in the after-run, it is a patch
regression even when that finding's fingerprint is `novelty="known"` against the
trusted baseline.

Budget payloads use `null` for disabled numeric thresholds rather than sentinel
values. Boolean policy gates are named `forbid_*`, for example
`forbid_dead_code_regression`.
## Verify Ergonomics

`check_patch_contract(mode="verify")` includes three ergonomic features that
reduce agent error and wasted context tokens.

### Auto-resolve before_run_id

When `intent_id` is provided but `before_run_id` is omitted, verify resolves
the before-run from the intent record's `run_id`. This eliminates the most
common agent error: forgetting to pass `before_run_id`.

### Next-step hints

Non-accepted verify responses include a `next_step` field with an actionable
hint matched to the failure reason:

| Reason                              | Hint                                                       |
|-------------------------------------|------------------------------------------------------------|
| `no_before_run`                     | Run analysis or pass intent_id to auto-resolve             |
| `no_after_run`                      | Run analysis after editing and pass after_run_id           |
| `after_run_not_new`                 | After-run matches before-run; run fresh post-edit analysis |
| `after_run_required_for_governance` | Governance changes require post-edit analysis              |
| `incomparable_runs`                 | Re-run analysis with the same settings                     |
| `intent_not_active`                 | Queued intent must be promoted first                       |
| `report_digest_mismatch`            | Use the original intent_id with the original before-run    |
| `state_artifact_mutation`           | Remove baseline/cache files from the patch                 |
| `scope_violation`                   | Redeclare intent with expanded scope                       |

### Claim validation recommended

The `claim_validation_recommended` boolean in verify responses advises whether
calling `validate_review_claims` is meaningful for the verification profile.
It is `true` for `python_structural` and `governance_config` profiles, `false`
for `documentation_only`, `non_python_patch`, `state_artifact_change`, and
non-accepted outcomes.
## Workflow consolidation

The atomic change control workflow requires 7–11 MCP tool calls per edit
cycle. Two **workflow-level tools** aggregate these steps while preserving
the same evidence, state updates, and boundary checks:

| Tool                       | Replaces                                          | Calls            |
|----------------------------|---------------------------------------------------|------------------|
| `start_controlled_change`  | workspace check + declare + blast radius + budget | 1 instead of 4   |
| `finish_controlled_change` | scope check + verify + claims + receipt + clear   | 1 instead of 4–6 |

Workflow tools are orchestration shortcuts. They call the same internal
methods as the atomic tools and emit the same semantic audit events.
`analyze_repository` remains a separate explicit call — workflow tools
never run analysis implicitly.

`finish_controlled_change` keeps human notes and validated claims separate:
`review_text` is a note, while `claims_text` is the only finish parameter passed
to Claim Guard. The response includes a compact `summary` for humans while
retaining full `scope_check`, `verification`, `claims`, `receipt`, and
`workspace_hygiene_after` payloads for agents.

**Tool tiers:**

- **Normal workflow:** `analyze_repository`, `start_controlled_change`,
  `finish_controlled_change` — every edit cycle.
- **Queue/recovery:** `manage_change_intent` (promote, recover, reset,
  renew) — multi-agent coordination, crash recovery.
- **Advanced/diagnostic:** `get_blast_radius`, `check_patch_contract`,
  `validate_review_claims`, `create_review_receipt` — deep inspection,
  step-by-step debugging.

The same semantic audit events are preserved regardless of which
approach the agent uses. Atomic tools remain available for backward
compatibility and advanced use cases.
