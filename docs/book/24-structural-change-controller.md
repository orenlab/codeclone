# Structural Change Controller

CodeClone v2.1 adds a session-local MCP control layer for AI-assisted edits.
The controller is not a second analyzer and does not persist state. It composes
over stored MCP runs and the canonical report contract.

## Status

The v2.1 alpha currently includes intent, blast-radius, patch-contract checks,
and review receipts:

| Phase | Status | MCP surface |
|-------|--------|-------------|
| Intent declaration | Live in `2.1.0a1` | `manage_change_intent` |
| Blast radius | Live in `2.1.0a1` | `get_blast_radius` |
| Patch contract | Live in `2.1.0a1` | `check_patch_contract` |
| Review receipt | Live in `2.1.0a1` | `create_review_receipt` |
| Claim guard | Planned | `validate_review_claims` |

Claim guard is a roadmap item until implemented and tested. Public clients
must not assume it exists in the current MCP tool list.

## Contract

- The canonical report remains the source of truth.
- Controller state is session-local and in-memory.
- MCP must not mutate source files, baselines, cache, reports, or repo state.
- Tools derive responses from existing run/report facts rather than LLM
  inference.
- Report-only context is review context, not an edit prohibition.

## Pre-Change Workflow

1. Run `analyze_repository` or `analyze_changed_paths`.
2. Declare scope with `manage_change_intent(action="declare")`.
3. Inspect the returned `blast_radius_summary`.
4. Optionally call `get_blast_radius` for full dependent/context detail.
5. Call `check_patch_contract(mode="budget")` to inspect the active regression
   budget and metric headroom before editing.
6. After editing, call `manage_change_intent(action="check")` with
   `changed_files` or `diff_ref`.
7. Run analysis again, then call `check_patch_contract(mode="verify")` with
   explicit `before_run_id` and `after_run_id`.
8. Call `create_review_receipt` to collect provenance, scope, blast radius,
   reviewed findings, patch status, human decision points, and claims-not-made.

`manage_change_intent` can return `clean`, `expanded`, `violated`, or
`expired`. Expiry means the report digest changed since declaration.

`check_patch_contract` never runs analysis itself. Budget mode reads one stored
run and optional intent. Verify mode compares explicit before/after stored runs,
previews gates, validates scope when intent is available, and reports baseline
abuse signals. Missing before or after runs return `status="unverified"` with
`reason="no_before_run"` or `reason="no_after_run"`.

## Blast Radius Payload

`get_blast_radius` separates hard edit guardrails from review context:

- `do_not_touch`: actionable negative context such as baseline/cache state,
  explicit forbidden paths, or affected files outside declared scope.
- `review_context`: report-only facts such as security boundary inventory,
  overloaded-module candidates, known baseline debt, and golden fixture
  surfaces.

Long context sections are bounded and include summaries with `total`, `shown`,
and `truncated`.

## Review Receipt Payload

`create_review_receipt` returns `format="markdown"` by default and can return a
structured JSON receipt with `format="json"`. The receipt is a composition of
stored MCP state; it does not run analysis and does not mutate source files,
baselines, cache, reports, or repository state.

The receipt includes:

- report provenance: digest, schema version, baseline trust state, run id, root
- scope: optional change intent, declared files, changed files, unexpected files
- blast radius summary: level, direct dependent count, clone cohort count,
  do-not-touch count
- reviewed evidence: session-local reviewed finding markers and notes
- patch contract: accepted, violated, or not checked from stored gate,
  structural delta, intent, and baseline-abuse signals
- human decision points: bounded list of clone divergence, scope expansion, and
  known-baseline-debt prompts
- claims not made: explicit reminders that Security Surfaces are boundary
  inventory, report-only signals are not gates, and known baseline debt is not a
  new regression

Receipt verdicts are `clean`, `incomplete`, or `needs_attention`. They summarize
receipt completeness only; they are not CI gates.
