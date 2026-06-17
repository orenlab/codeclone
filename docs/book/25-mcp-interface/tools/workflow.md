### Workflow tools (preferred)

| Tool                       | Key parameters                                                                                                                                                                                 | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
|----------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `start_controlled_change`  | `root`, `scope`, `intent`, `expected_effects`, `on_conflict`, `strictness`, `ttl_seconds`, `blast_radius_depth`, `dirty_scope_policy`                                                          | Pre-edit: workspace check + declare + blast radius + budget in one call. Returns `intent_id` for `finish`. `ttl_seconds` overrides intent lifetime (default `3600`, env `CODECLONE_INTENT_TTL_SECONDS` when omitted). `dirty_scope_policy=continue_own_wip` resumes known dirty scope when no foreign overlap. Does not run analysis                                                                                                                                                                                                                      |
| `finish_controlled_change` | `intent_id`, `changed_files` or `diff_ref`, `after_run_id`, `review_text`, `claims_text`, `propose_memory`, `create_receipt`, `auto_clear`, `strictness`, `detail_level`, `patch_trail_detail` | Post-edit pipeline: hygiene gate → scope check → verify → Patch Trail + audit → optional claims → receipt → clear. `after_run_id` required for Python structural / governance config profiles. Hygiene: `detail_level="full"` for per-path attribution; otherwise counts/blocking only. `patch_trail_detail`: `summary` (default) or `full` path lists on `patch_trail`. Top-level `status` may be `accepted_with_external_changes` when verify passes but out-of-scope git dirt remains. Set `propose_memory=true` for draft memory candidates on accept |

`finish_controlled_change` separates human notes from validated claims:
`review_text` is an optional note, while `claims_text` is the text passed to
Claim Guard. The response includes a compact `summary` plus the full
`scope_check`, `verification`, `claims`, `receipt`, and `workspace_hygiene_after`
payloads. When `create_receipt` fails, verify may still be `accepted` but
`intent_cleared` stays `false`.

??? info "Start/finish workspace hygiene"
    Edit permission requires `start_controlled_change` to return
    `status == "active"` **and** `edit_allowed == true`. Workflow
    `status: "blocked"` is not persisted registry lifecycle. Start may attach
    scoped `workspace_hygiene`; finish runs `finish_hygiene_check` before check/verify.
    Hygiene path detail (`dirty_attribution`, classification arrays) requires
    `detail_level="full"`; `summary`/`normal` return counts and blocking fields only.
    **Blocking finish** (`reason: workspace_hygiene`, `blocks_finish: true`) happens
    for `finish_block_reason` `missing_evidence`, `foreign_dirty_overlap`, and
    (when strict finish mode is enabled) `own_unscoped_dirty`. Out-of-scope
    unattributed dirt is **advisory** — it may surface as `external_changes` and
    elevate top-level status to `accepted_with_external_changes` without failing
    verify. Unchanged preexisting out-of-scope dirty is informational. Foreign
    active/stale dirt outside your scope → `foreign_attributed_outside_scope`
    (ignored). Recoverable intents do not grant foreign attribution. Queued
    foreign intents do not populate `foreign_dirty_overlaps`. `files_for_scope_check`
    is agent evidence only. Full pipeline and field reference:
    [finish_controlled_change](../../12-structural-change-controller/finish-controlled-change.md).
    `manage_change_intent(list_workspace)` returns repo-level
    `workspace_dirty_summary` only. Registry lazy close vs `gc_workspace`: see
    [Workspace hygiene and registry consistency](../../12-structural-change-controller/finish-hygiene.md).
