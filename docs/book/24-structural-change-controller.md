# Structural Change Controller

CodeClone v2.1 adds a session-local MCP control layer for AI-assisted edits.
The controller is not a second analyzer and does not persist state. It composes
over stored MCP runs and the canonical report contract.

## Status

The v2.1 alpha starts with the pre-change phase:

| Phase | Status | MCP surface |
|-------|--------|-------------|
| Intent declaration | Live in `2.1.0a1` | `manage_change_intent` |
| Blast radius | Live in `2.1.0a1` | `get_blast_radius` |
| Patch contract | Planned | `check_patch_contract` |
| Review receipt | Planned | `create_review_receipt` |
| Claim guard | Planned | `validate_review_claims` |

Planned tools are roadmap items until implemented and tested. Public clients
must not assume they exist in the current MCP tool list.

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
5. After editing, call `manage_change_intent(action="check")` with
   `changed_files` or `diff_ref`.

`manage_change_intent` can return `clean`, `expanded`, `violated`, or
`expired`. Expiry means the report digest changed since declaration.

## Blast Radius Payload

`get_blast_radius` separates hard edit guardrails from review context:

- `do_not_touch`: actionable negative context such as baseline/cache state,
  explicit forbidden paths, or affected files outside declared scope.
- `review_context`: report-only facts such as security boundary inventory,
  overloaded-module candidates, known baseline debt, and golden fixture
  surfaces.

Long context sections are bounded and include summaries with `total`, `shown`,
and `truncated`.
