<!-- doc-scope: Agent edit cycle recipe. class: guide max-lines: 120 -->
# Agent edit cycle

Same sequence as [MCP change control workflow](../mcp/workflows/change-control.md).

**Before first edit:** `start_controlled_change` must return `status: active` and
`edit_allowed: true`. Queued intents require `manage_change_intent(action=promote)`.

**Evidence:** finish requires exactly one of `changed_files` or `diff_ref` listing
every in-scope dirty path.

**After-run:** required when verification profile is `python_structural` or
`governance_config`. Pass a **new** `after_run_id` — identical before/after runs
return `after_run_not_new`.

**Claims:** only `claims_text` goes to Claim Guard; `review_text` is a human note.

**Memory:** call `get_relevant_memory` after start; optional
`finish(..., propose_memory=true)` for draft candidates (human approve in VS Code
Memory view).

Contract tables: [Verification profiles](../../book/12-structural-change-controller/verification-profiles.md),
[finish_controlled_change](../../book/12-structural-change-controller/finish-controlled-change.md).
