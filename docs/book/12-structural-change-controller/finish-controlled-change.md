## `finish_controlled_change`

Post-edit workflow tool. It runs a **fixed pipeline** over the same atomic
primitives as the manual path; agents must not skip hygiene, check, or verify
and call `clear` alone.

### Preconditions

- Intent is **active** in the current MCP session (not `queued`).
- **Evidence:** exactly one of `changed_files` or `diff_ref` (non-empty). Both
  or neither is a contract error.
- **`after_run_id`** when the derived `verification_profile` requires it
  (Python structural and governance config patches).

`review_text` is a human note only. **`claims_text`** is the only finish input
passed to Claim Guard (when `claim_validation_recommended` is true).

### Execution order (do not reorder manually)

```text
resolve intent
  → resolve changed_files | diff_ref (git-expanded)
  → finish_hygiene_check (git + start dirty snapshot)
  → manage_change_intent(check)  # uses files_for_scope_check = evidence only
  → check_patch_contract(verify) # before_run_id from intent when omitted
  → compute Patch Trail + audit emit patch_trail.computed (when check/verify reached)
  → validate_review_claims (optional, if claims_text + recommended)
  → create_review_receipt (default true)
  → manage_change_intent(clear)  # auto_clear when accepted and receipt ok
  → elevate status if out-of-scope dirty remains (external_changes)
```

Early exits (intent stays active unless noted):

| Step                | Top-level `status`                             | `reason` (typical)      | `intent_cleared`                          |
|---------------------|------------------------------------------------|-------------------------|-------------------------------------------|
| Queued intent       | `unverified`                                   | `intent_not_active`     | `false`                                   |
| Hygiene gate        | `unverified`                                   | `workspace_hygiene`     | `false`                                   |
| Scope check         | `expired` / `violated`                         | digest / scope          | `false`                                   |
| Verify not accepted | `unverified` / `violated`                      | verify-specific         | `false`                                   |
| Receipt failure     | `accepted` or `accepted_with_external_changes` | —                       | `false` (verify passed but clear skipped) |
| Success             | `accepted` or `accepted_with_external_changes` | verify reason or `null` | `true` when `auto_clear` and receipt ok   |

### Top-level `status` semantics

| `status`                         | Meaning for agents                                                                                                                            |
|----------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| `accepted`                       | Patch contract passed for declared scope; no out-of-scope dirty paths in the hygiene view                                                     |
| `accepted_with_external_changes` | Patch contract passed; **other** git-dirty paths exist outside declared scope — report `external_changes` to the user; intent may still clear |
| `unverified`                     | Hygiene block, verify failure, missing after-run, `after_run_not_new`, etc. — follow `next_step`                                              |
| `violated`                       | Scope expansion or structural/gate violations attributable to the patch                                                                       |
| `expired`                        | Before-run digest no longer matches intent — re-analyze and `start` again                                                                     |

`accepted` / `accepted_with_external_changes` mean the **patch contract** passed
for the declared scope. They do **not** mean “no structural regressions” or
unchanged repository health — read `verification.structural_delta` and
`health_regression_advisory` when present.

### Hygiene payload `detail_level`

On `start_controlled_change` / `finish_controlled_change`, hygiene uses
`detail_level` as binary size control: `summary` and `normal` are equivalent
(`counts`, `foreign_dirty_overlaps`, blocking flags). `detail_level="full"` adds
`dirty_attribution`, path classification arrays, and expanded `dirty_snapshot`.
Findings/hotspots tools still honor all three levels.

### Response payloads agents should read

| Field                           | Use                                                                                                   |
|---------------------------------|-------------------------------------------------------------------------------------------------------|
| `summary`                       | Compact dashboard (`scope_status`, `verification_profile`, `receipt`, `intent_cleared`, dirty counts) |
| `scope_check`                   | Declared vs actual files from check                                                                   |
| `verification`                  | Full verify payload including `structural_delta`, `next_step`                                         |
| `workspace_hygiene_after`       | Post-finish hygiene; `counts` always; `dirty_attribution` only when `detail_level="full"`             |
| `health_regression_advisory`    | On accepted verify when `health_delta < 0` — user-facing, not auto-fail                               |
| `claims`                        | Claim Guard result when `claims_text` was validated                                                   |
| `receipt` / `receipt_error`     | Receipt body; `receipt_error` prevents `auto_clear`                                                   |
| `propose_memory` / memory hooks | When `propose_memory=true` on accept                                                                  |
| `patch_trail`                   | Deterministic scope/verify forensics for this finish (see below); not authorization                   |
| `projection_rebuild`            | Optional job enqueue on accept when projection policy is not `off` (non-CI)                           |

Markdown receipt payloads expose top-level `receipt_version`, `verdict`,
`receipt_digest`, `content`, and `receipt_retrieval` for compact identity and
human review. The duplicate nested typed receipt is not returned by default;
fetch the complete structured receipt after `auto_clear=true` with
`get_review_receipt(root, run_id, receipt_digest, format="structured")`.

`context_governance` measures the complete finish response as one payload and
publishes a `finish_projection_v1` digest under
`context_governance.response`. Finish responses use `mode="partial_enforce"` and
`evidence_policy="response_budget_with_durable_artifact_lookup"`: mandatory
control, scope, verification, hygiene, and action fields stay inline, while
recoverable advisory lanes may be compacted. When receipt markdown content or
Patch Trail detail is omitted, `context_governance.omitted` carries exact
drill-down metadata for `get_review_receipt` or `get_patch_trail`.

### Patch Trail on finish

Patch Trail is computed when scope `check` reaches `violated` (**before**
verify) or when check is `clean` / `expanded` and verify runs — including
failed verify (`unverified` / `violated` top-level status). Hygiene blocks and
`expired` intents do **not** emit Patch Trail.

Normative diagram and fields: [Patch Trail](patch-trail.md).

### Post-success hooks (accept only)

When verify status is `accepted` or `accepted_with_external_changes`:

- `propose_memory=true` runs finish-side memory proposals and staleness updates.
- `maybe_auto_enqueue_projection_rebuild` may return `projection_rebuild` when
  `memory.projection_rebuild_policy` is not `off` and the process is not CI.

Receipt creation and `auto_clear` still follow the table above; a receipt error
leaves the intent active even when verify passed.

Refs:

- `codeclone/surfaces/mcp/_session_workflow_mixin.py:finish_controlled_change`
- `codeclone/memory/jobs/workflow.py:maybe_auto_enqueue_projection_rebuild`
