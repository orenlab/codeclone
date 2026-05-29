# Structural Change Controller

CodeClone v2.1 adds structural change control for AI-assisted edits. The MCP
surface owns session-aware agent workflows; the CLI exposes the two
human-facing query modes that are useful at a terminal. Neither path is a
second analyzer: both compose over the canonical report contract.

## Status

The v2.1 alpha currently includes intent, blast-radius, patch-contract checks,
review receipts, workspace intent visibility, claim guard, and CLI controller
queries:

| Phase                       | Status            | Surface                                          |
|-----------------------------|-------------------|--------------------------------------------------|
| Intent declaration          | Live in `2.1.0a1` | MCP `manage_change_intent`                       |
| Blast radius                | Live in `2.1.0a1` | MCP `get_blast_radius`, CLI `--blast-radius`     |
| Patch contract              | Live in `2.1.0a1` | MCP `check_patch_contract`, CLI `--patch-verify` |
| Review receipt              | Live in `2.1.0a1` | MCP `create_review_receipt`                      |
| Workspace intent registry   | Live in `2.1.0a1` | MCP `manage_change_intent`                       |
| Lease and recovery          | Live in `2.1.0a1` | MCP `manage_change_intent`                       |
| Claim guard                 | Live in `2.1.0a1` | MCP `validate_review_claims`                     |
| Scope-aware verification    | Live in `2.1.0a1` | MCP `check_patch_contract`                       |
| Workspace relations         | Live in `2.1.0a1` | MCP `manage_change_intent`                       |
| Verification profiles       | Live in `2.1.0a1` | MCP `check_patch_contract`                       |
| Intent queue                | Live in `2.1.0a1` | MCP `manage_change_intent`                       |
| Verify ergonomics           | Live in `2.1.0a1` | MCP `check_patch_contract`                       |
| MCP payload token budget    | Live in `2.1.0a1` | Audit trail, CLI `--audit`, `--session-stats`    |

## Contract

- The canonical report remains the source of truth.
- Intent truth is session-local and in-memory.
- MCP may write ephemeral workspace coordination records under
  `.cache/codeclone/intents/`.
- MCP must not mutate source files, baselines, reports, or analysis cache data.
- Tools derive responses from existing run/report facts rather than LLM
  inference.
- Report-only context is review context, not an edit prohibition.

## CLI Controller Queries

The CLI exposes read-only terminal projections for humans:

```bash
codeclone . --blast-radius codeclone/core/parser.py
codeclone . --patch-verify --diff-against HEAD~1
codeclone . --patch-verify --strictness relaxed
codeclone . --session-stats
```

`--blast-radius` runs normal analysis, builds the canonical report in memory,
and renders the same dependent/context split as `get_blast_radius`.

`--patch-verify` uses the trusted clone baseline as the accepted before-state
and the current working tree as after-state. It checks new clone regressions and
the selected gate profile. `ci` is the default; `strict` applies tighter
controller budgets; `relaxed` reports violations but exits `0`.

`--session-stats` shows workspace session status: active agents, intents, and
lease health. Read-only, does not run analysis.

CLI controller queries are terminal-only and read-only with respect to source
files, baselines, reports, and analysis cache data. They are incompatible with
report output flags and baseline update flags.

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
11. Call `validate_review_claims` before publishing a review summary.
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
- `renew`: refresh the active lease before long edits or test runs.
- `gc_workspace`: remove expired, orphaned, or corrupted registry records.
- `recover`: explicitly reclaim a recoverable intent when the caller has the
  matching run and report digest in the current MCP session.
- `reset_workspace`: reset an own intent or remove expired/recoverable
  registry records. Foreign active and foreign stale intents are rejected
  and require coordination.

Registry files live under `.cache/codeclone/intents/` and are protected with a
SHA-256 integrity digest over canonical JSON. This detects accidental
corruption, not malicious tampering by a user with write access. Conflicts are
advisory: hard overlap means two agents claimed the same primary file; soft
overlap means primary files overlap related context.

Each registry record has a TTL and a shorter renewable lease. TTL is the hard
maximum lifetime of the record (default 3600s). The lease is the ownership
freshness signal (default 300s, max 600s): active MCP interactions auto-renew
it, while detached processes stop renewing and transition through ownership
states.

??? info "Ownership classification"

    | State            | PID alive | Lease valid | Meaning                                              |
    |------------------|-----------|-------------|------------------------------------------------------|
    | `own_active`     | own       | yes         | This session's active intent                         |
    | `own_stale`      | own       | no          | This session's intent with expired lease             |
    | `foreign_active` | foreign   | yes         | Another live process, active lease — coordinate      |
    | `foreign_stale`  | foreign   | no          | Another live process, expired lease — coordinate     |
    | `recoverable`    | dead      | —           | Owning process is dead; safe to reclaim              |
    | `expired`        | —         | —           | TTL exceeded; eligible for garbage collection        |

    A foreign active or foreign stale record should be coordinated with the
    user; CodeClone does not ask agents to kill the owning process. Only
    `recoverable` intents (dead PID) can be reclaimed without user
    coordination.

## Review Receipt Payload

`create_review_receipt` returns `format="markdown"` by default and can return a
structured JSON receipt with `format="json"`. The receipt is a composition of
stored MCP state; it does not run analysis and does not mutate source files,
baselines, cache, reports, or repository state.

The receipt includes:

- report provenance: digest, schema version, baseline trust state, run id, root
- verification profile: profile classification, reason, applicable/not-applicable
  checks, limitations
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

## Verification Profiles

`check_patch_contract(mode="verify")` derives a **verification profile** from
actual changed files. The profile determines which structural checks are
applicable and whether `after_run_id` is required for verification.

### Profile classification

The classifier is a pure function with a deterministic priority chain:

| Priority | Profile                | When                                    | `after_run` required | Structural checks |
|----------|------------------------|-----------------------------------------|----------------------|-------------------|
| 1        | `state_artifact_change`| Baseline or cache files touched         | no (violated)        | not applicable    |
| 2        | `python_structural`    | Any `.py` / `.pyi` touched              | yes                  | all               |
| 3        | `governance_config`    | Config files only (pyproject.toml, CI…) | yes                  | not applicable    |
| 4        | `documentation_only`   | Only docs files (`.md`, `.rst`, …)      | no                   | not applicable    |
| 5        | `non_python_patch`     | Other files, no Python or docs          | no                   | not applicable    |

A single file from a higher-priority category overrides the entire patch.

### Fast path

Documentation-only and non-Python patches can verify without `after_run_id`
when `changed_files` or `diff_ref` evidence is provided. Without any diff
evidence, verify returns `unverified` to preserve backward compatibility.

### Invariants

- The profile is derived from `actual_changed_files`, never declared by the
  agent.
- Scope and forbidden checks always run before any profile-based fast return.
- Receipts use "not applicable" for skipped structural checks, never "passed".
- Claim guard warns when review text references structural verification but
  the profile says structural checks were not applicable.

### Public surface

| Artifact              | Path                                                              |
|-----------------------|-------------------------------------------------------------------|
| Classifier module     | `codeclone/surfaces/mcp/_verification_profile.py`                 |
| Enum                  | `VerificationProfile`                                             |
| Classifier            | `classify_patch(changed_files) → ClassificationResult`            |
| Check matrix          | `check_matrix(profile) → CheckMatrix`                             |

### Locked by tests

- `tests/test_verification_profile.py`
- `tests/test_mcp_service.py`

## Scope-Aware Patch Contract Verification

When a change intent is active, `check_patch_contract(mode="verify")` attributes
regressions and gate changes to the declared scope rather than treating the
entire workspace as one undifferentiated surface.

### Regression attribution

Regressions from `compare_runs` are partitioned into two sets:

- `intent_regressions` — findings whose file paths fall inside the declared
  `allowed_files` or `allowed_related`.
- `external_regressions` — findings whose file paths are entirely outside
  the declared scope.

Only `intent_regressions` produce `structural_regressions` contract violations.
External regressions are reported as informational context without failing the
contract.

Findings with no extractable file paths are conservatively classified as
intent-scope to avoid false-negative accepts.

Without an active intent, all regressions are treated as intent-scope and
behavior is unchanged from the base contract.

### Gate-delta logic

Gate evaluation uses a two-layer attribution model:

1. **Gate delta** — only gate *changes* between before-run and after-run are
   contract-relevant. A gate that was already failing before the edit is
   pre-existing, not a new violation. `gate_worsened` is true only when
   `before_gate.would_fail` is false and `after_gate.would_fail` is true.

2. **Gate attribution** — when `gate_worsened` is true and an intent is active,
   the contract checks whether the gate-triggering signals come from intent
   scope: intent-scope regressions or intent-scope worsened metric symbols. If
   neither exists, the gate failure is external and does not produce a contract
   violation.

### Status values

| Status                          | Meaning                                                |
|---------------------------------|--------------------------------------------------------|
| `accepted`                      | No intent-scope regressions, no gate worsening         |
| `accepted_with_external_changes`| Intent scope is clean but external signals exist       |
| `violated`                      | Intent-scope regressions, intent-caused gate failure, or scope violation |
| `unverified`                    | Missing before or after run                            |
| `expired`                       | Report digest mismatch since declaration               |

The `accepted_with_external_changes` status signals that another agent or
concurrent edit introduced regressions outside the current intent scope. The
verify response includes `intent_regressions`, `external_regressions`,
`intent_worsened`, `external_worsened`, `gate_worsened`, and `before_gate`
fields for full attribution visibility.

??? info "Decision table"

    | Intent | Intent regressions | External regressions | Gate worsened | Intent caused gate | Scope check | Status                           |
    |--------|--------------------|-----------------------|---------------|--------------------|-------------|----------------------------------|
    | no     | any                | —                     | any           | any                | —           | current logic unchanged          |
    | yes    | > 0                | any                   | any           | any                | any         | `violated`                       |
    | yes    | 0                  | any                   | yes           | yes                | clean       | `violated`                       |
    | yes    | 0                  | any                   | yes           | no                 | clean       | `accepted_with_external_changes` |
    | yes    | 0                  | > 0                   | no            | —                  | clean       | `accepted_with_external_changes` |
    | yes    | 0                  | 0                     | no            | —                  | clean       | `accepted`                       |
    | yes    | 0                  | any                   | any           | any                | violated    | `violated` (scope violation)     |

### Baseline abuse

`detect_baseline_abuse` stays workspace-global. Baseline hygiene is a
repository-level signal: if the baseline was updated while any regressions exist
(even external), that is suspicious regardless of whose regressions they are.

## Workspace Relations

`detect_conflicts` classifies the relationship between a new intent and existing
workspace intents. Beyond edit-overlap detection (hard and soft conflicts),
the classifier distinguishes forbidden-scope relationships:

| Relation                  | Meaning                                               |
|---------------------------|-------------------------------------------------------|
| `edit_overlap`            | Both agents claim the same files (hard or soft)       |
| `foreign_excludes_target` | Foreign `forbidden` matches current `allowed_files`   |
| `target_excludes_foreign` | Current `forbidden` matches foreign `allowed_files`   |

Absence of a relation entry means disjoint scope.

The `declare` response includes a `workspace_relations` field alongside the
existing `concurrent_intents`. `concurrent_intents` continues to contain only
edit overlaps for backward compatibility; `workspace_relations` provides the
full classification including forbidden-scope signals.

This allows agents to distinguish three cases that were previously
indistinguishable:

1. No overlap at all (disjoint).
2. No edit overlap, but the foreign agent explicitly excludes the current
   agent's target files (`foreign_excludes_target`) — a positive coordination
   signal.
3. No edit overlap, but the current agent explicitly excludes the foreign
   agent's target files (`target_excludes_foreign`).

## Intent Queue

When multiple agents target overlapping scope, `manage_change_intent` supports
an advisory queue so a blocked agent can register its intent without failing.

### Declare with queue

`manage_change_intent(action="declare", on_conflict="queue")` first attempts a
normal declare. If `detect_conflicts` finds overlapping foreign active intents,
it downgrades the already-registered intent to `queued` instead of returning an
error.

A queued intent:

- Is visible in `list_workspace` as a workspace record with `status="queued"`.
- Does **not** own scope — conflict detection skips queued records.
- Does **not** pin the before-run — long waits may cause eviction from bounded
  run history.
- Cannot pass `check_patch_contract(mode="verify")` or
  `check_patch_contract(mode="budget")` with `edit_allowed=true`.
- Can be cleared via `manage_change_intent(action="clear")`.

The declare response includes `blocked_by` (list of blocking intents with
`intent_id`, `agent_pid`, `ownership`, `overlapping_files`) and
`queue_position` (deterministic ordering by `declared_at_utc`, then
`intent_id`).

### Promote

`manage_change_intent(action="promote", intent_id=...)` transitions a queued
intent to active:

1. Validates the intent has `status="queued"`.
2. Resolves the before-run — if evicted, returns `status="unverified"` with
   `reason="before_run_evicted"` and a `next_step` hint.
3. Re-checks workspace conflicts. If conflicts persist, returns `status="queued"`
   with `blocking_count` and `blocked_by` without changing state.
4. On success: sets status to `active`, pins the run, renews the lease, and
   updates the workspace record.

### Queue semantic invariants

- `queued` is a lifecycle status, not an ownership classification. Ownership
  (`own_active`, `foreign_active`, etc.) and status (`active`, `queued`) are
  orthogonal.
- Queued intents do not block other agents. `_detect_scope_state` skips records
  with `status == "queued"`.
- Queue position is deterministic: sorted by `declared_at_utc`, then
  `intent_id` as tiebreaker.

### Audit events

| Event                  | When                           |
|------------------------|--------------------------------|
| `intent.queued`        | Declare downgrades to queued   |
| `intent.promoted`      | Promote succeeds               |
| `intent.queue_blocked` | Promote blocked by conflicts   |

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

| Reason                              | Hint                                                    |
|-------------------------------------|---------------------------------------------------------|
| `no_before_run`                     | Run analysis or pass intent_id to auto-resolve          |
| `no_after_run`                      | Run analysis after editing and pass after_run_id        |
| `after_run_required_for_governance` | Governance changes require post-edit analysis           |
| `incomparable_runs`                 | Re-run analysis with the same settings                  |
| `intent_not_active`                 | Queued intent must be promoted first                    |
| `report_digest_mismatch`            | Use the original intent_id with the original before-run |
| `state_artifact_mutation`           | Remove baseline/cache files from the patch              |
| `scope_violation`                   | Redeclare intent with expanded scope                    |

### Claim validation recommended

The `claim_validation_recommended` boolean in verify responses advises whether
calling `validate_review_claims` is meaningful for the verification profile.
It is `true` for `python_structural` and `governance_config` profiles, `false`
for `documentation_only`, `non_python_patch`, `state_artifact_change`, and
non-accepted outcomes.

## MCP Payload Token Budget

The optional controller audit trail can estimate the token footprint of MCP
payloads returned to the agent. This is a deterministic estimate of how much
context window each tool response consumes, not actual model billing tokens.

### Setup

Token estimation requires two conditions:

1. Audit trail enabled (`audit_enabled = true` in `pyproject.toml`).
2. The `codeclone[token-bench]` optional extra installed (provides `tiktoken`).

Without `tiktoken`, the estimator falls back to a character-based approximation
(`ceil(characters / 4)`). Without audit enabled, no estimation runs.

### How it works

The estimation runs inside the audit writer's `event_to_row`, not in the MCP
tool call path. The MCP session has zero overhead when audit is disabled or
when `tiktoken` is not installed.

Each audit event row includes three optional fields:

- `estimated_tokens` — BPE token count (or character-based approximation).
- `token_encoding` — encoding name (`o200k_base` or `chars_approx`).
- `payload_characters` — character count of the canonical JSON payload.

The estimation input is the full original payload (what the MCP client
receives), not the compact audit storage form.

### CLI visibility

The `--audit` Rich TUI renderer shows token columns when data is available:

```
Tokens  Encoding      Event
  412   o200k_base    intent.declared
  890   o200k_base    blast_radius.computed
 1204   o200k_base    patch_contract.verified
```

The `--session-stats` command appends a summary line when audit token data
exists:

```
MCP payload footprint: ~3,816 tokens (o200k_base, 7 tool calls)
```

### Invariants

- Token estimation never affects controller decisions, gate results, report
  digests, or baseline trust.
- Any exception in the estimation path results in `NULL` values, not a failed
  audit event write.
- The `codeclone/budget/` module never imports from `codeclone/surfaces/` or
  `codeclone/audit/`. Dependency direction: `audit -> budget`, never reverse.
- Base `codeclone` never depends on `tiktoken`. The import is lazy and guarded.
