# Structural Change Controller

CodeClone v2.1 adds an MCP control layer for AI-assisted edits. The controller
is not a second analyzer. It composes over stored MCP runs and the canonical
report contract.

## Status

The v2.1 alpha currently includes intent, blast-radius, patch-contract checks,
review receipts, workspace intent visibility, and claim guard:

| Phase | Status | MCP surface |
|-------|--------|-------------|
| Intent declaration | Live in `2.1.0a1` | `manage_change_intent` |
| Blast radius | Live in `2.1.0a1` | `get_blast_radius` |
| Patch contract | Live in `2.1.0a1` | `check_patch_contract` |
| Review receipt | Live in `2.1.0a1` | `create_review_receipt` |
| Workspace intent registry | Live in `2.1.0a1` | `manage_change_intent` |
| Claim guard | Live in `2.1.0a1` | `validate_review_claims` |

## Contract

- The canonical report remains the source of truth.
- Intent truth is session-local and in-memory.
- MCP may write ephemeral workspace coordination records under
  `.cache/codeclone/intents/`.
- MCP must not mutate source files, baselines, reports, or analysis cache data.
- Tools derive responses from existing run/report facts rather than LLM
  inference.
- Report-only context is review context, not an edit prohibition.

## Pre-Change Workflow

1. Call `manage_change_intent(action="list_workspace", root="/abs/repo")` to
   see active intents from other agents before analysis.
2. Run `analyze_repository` or `analyze_changed_paths`.
3. Declare scope with `manage_change_intent(action="declare")`.
4. If `concurrent_intents` is non-empty, narrow scope or coordinate before
   editing.
5. Inspect the returned `blast_radius_summary`.
6. Optionally call `get_blast_radius` for full dependent/context detail.
7. Call `check_patch_contract(mode="budget")` to inspect the active regression
   budget and metric headroom before editing.
8. After editing, call `manage_change_intent(action="check")` with
   `changed_files` or `diff_ref`.
9. Run analysis again, then call `check_patch_contract(mode="verify")` with
   explicit `before_run_id` and `after_run_id`.
10. Call `validate_review_claims` before publishing a review summary.
11. Call `create_review_receipt` to collect provenance, scope, blast radius,
   reviewed findings, patch status, human decision points, and claims-not-made.
12. Call `manage_change_intent(action="clear")` when the edit is complete.

`manage_change_intent` can return `clean`, `expanded`, `violated`, or
`expired`. Expiry means the report digest changed since declaration.

`check_patch_contract` never runs analysis itself. Budget mode reads one stored
run and optional intent. Verify mode compares explicit before/after stored runs,
previews gates, validates scope when intent is available, and reports baseline
abuse signals. Missing before or after runs return `status="unverified"` with
`reason="no_before_run"` or `reason="no_after_run"`.

Budget payloads use `null` for disabled numeric thresholds rather than sentinel
values. Boolean policy gates are named `forbid_*`, for example
`forbid_dead_code_regression`.

## Blast Radius Payload

`get_blast_radius` separates hard edit guardrails from review context:

- `do_not_touch`: actionable negative context such as baseline/cache state,
  generated CodeClone state, or explicit forbidden paths.
- `review_context`: report-only facts such as security boundary inventory,
  overloaded-module candidates, known baseline debt, and golden fixture
  surfaces.

Long context sections are bounded and include summaries with `total`, `shown`,
and `truncated`.

## Workspace Intent Registry

`manage_change_intent` also supports workspace actions for multi-agent
coordination:

- `list_workspace`: list active workspace intent records from all agents for a
  repository root.
- `gc_workspace`: remove expired, orphaned, or corrupted registry records.
- `reset_workspace`: recover an own, expired, or orphaned intent. Foreign live
  intents are rejected and require coordination.

Registry files live under `.cache/codeclone/intents/` and are protected with a
SHA-256 integrity digest over canonical JSON. This detects accidental
corruption, not malicious tampering by a user with write access. Conflicts are
advisory: hard overlap means two agents claimed the same primary file; soft
overlap means primary files overlap related context.

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

## Claim Guard

`validate_review_claims` validates review text against stored run semantics. It
uses citation matching around known finding ids and metric family names. It does
not read source files, run analysis, call an LLM, or persist state.

The guard checks for deterministic overclaims:

- Security Surfaces described as vulnerabilities or exploitability.
- Report-only metric families described as CI failures or blocking gates.
- known baseline findings described as new regressions.
- dead-code certainty where runtime reachability evidence exists.
- fixed/resolved claims before a post-patch run is available.

Warnings, such as missing or unknown citations, do not make the response
invalid. Violations make `valid=false`.
