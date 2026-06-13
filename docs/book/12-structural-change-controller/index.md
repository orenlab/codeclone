# Structural Change Controller

Normative contract for MCP/CLI change intent, blast radius, patch verification,
hygiene, receipts, and Patch Trail. Agent recipes live in the
[Change control guide](../../guide/change-control/overview.md).

## Status

The v2.1 alpha currently includes intent, blast-radius, patch-contract checks,
review receipts, workspace intent visibility, claim guard, and CLI controller
queries:

| Phase                     | Status            | Surface                                                                            |
|---------------------------|-------------------|------------------------------------------------------------------------------------|
| Declarative workflow      | Live in `2.1.0a1` | MCP `start_controlled_change`, `finish_controlled_change`                          |
| Intent declaration        | Live in `2.1.0a1` | MCP `manage_change_intent`                                                         |
| Blast radius              | Live in `2.1.0a1` | MCP `get_blast_radius`, CLI `--blast-radius`                                       |
| Patch contract            | Live in `2.1.0a1` | MCP `check_patch_contract`, CLI `--patch-verify`                                   |
| Review receipt            | Live in `2.1.0a1` | MCP `create_review_receipt`                                                        |
| Workspace intent registry | Live in `2.1.0a1` | MCP `manage_change_intent`                                                         |
| Lease and recovery        | Live in `2.1.0a1` | MCP `manage_change_intent`                                                         |
| Claim guard               | Live in `2.1.0a1` | MCP `validate_review_claims`                                                       |
| Scope-aware verification  | Live in `2.1.0a1` | MCP `check_patch_contract`                                                         |
| Workspace relations       | Live in `2.1.0a1` | MCP `manage_change_intent`                                                         |
| Verification profiles     | Live in `2.1.0a1` | MCP `check_patch_contract`                                                         |
| Intent queue              | Live in `2.1.0a1` | MCP `manage_change_intent`                                                         |
| Verify ergonomics         | Live in `2.1.0a1` | MCP `check_patch_contract`                                                         |
| MCP payload token budget  | Live in `2.1.0a1` | Audit trail, CLI `--audit`, `--session-stats`                                      |
| Patch Trail               | Live in `2.1.0a1` | MCP `finish_controlled_change(patch_trail_detail=…)`; audit `patch_trail.computed` |

## Contract

- The canonical report remains the source of truth.
- Intent truth is **session-local** for the active MCP process; the optional
  workspace registry (file backend under `.codeclone/intents/` or SQLite
  per `[tool.codeclone]`) provides advisory, TTL/lease-bound cross-process
  visibility only.
- MCP may write ephemeral workspace coordination records through the configured
  intent registry backend and optional audit records under
  `.codeclone/db/` when enabled.
- MCP must not mutate source files, baselines, reports, or analysis cache data.
- Tools derive responses from existing run/report facts rather than LLM
  inference.
- Report-only context is review context, not an edit prohibition.
  !!! note "Claim Guard"
  Full pattern catalog: [Claim Guard](../14-claim-guard.md).

## Chapters

| Topic                                  | Contract                                                |
|----------------------------------------|---------------------------------------------------------|
| CLI `--blast-radius`, `--patch-verify` | [CLI controller queries](cli-controller-queries.md)     |
| Blast radius & review receipt          | [Blast radius & receipt](blast-radius-and-receipt.md)   |
| Intent registry & queue                | [Intent registry & queue](intent-registry-and-queue.md) |
| Verification profiles                  | [Verification profiles](verification-profiles.md)       |
| Patch contract verify                  | [Patch contract verify](patch-contract-verify.md)       |
| Workflow tools                         | [Workflow tools](workflow-tools.md)                     |
| `finish_controlled_change`             | [finish_controlled_change](finish-controlled-change.md) |
| Finish hygiene                         | [Finish hygiene](finish-hygiene.md)                     |
| Patch Trail                            | [Patch Trail](patch-trail.md)                           |
| Payload semantics                      | [Payload semantics](payload-semantics.md)               |
| Token budget                           | [Token budget](token-budget.md)                         |
