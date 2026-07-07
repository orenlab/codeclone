# CodeClone — Claude Code Directives

## Identity

CodeClone is a deterministic structural controller for Python. Full architecture, contracts, and the agent playbook live
in `AGENTS.md`.

Code is the implementation source of truth. If docs and code diverge, follow code for implementation decisions and
report the divergence.

## Default role

Default role: **specs and validation only**.

Do not edit production code unless the user explicitly permits edits for a specific task. “Реализуй” / “Implement” is
explicit permission. “Проверь” / “Validate” is not.

When permitted to edit any tracked repository file — specs, tests, documentation, CI, coverage fixes, or docs-only
changes included — follow the change-control workflow. Task type never skips `start`. When CodeClone MCP is available,
read the bundled `codeclone-change-control` skill for the full pipeline (tool tiers, decision tables, profiles).

## Change-control workflow

The protocol is mandatory. The derived verification profile controls which steps are required, but `start` is always
required before edits.

Profiles:

| Profile                               | Workflow                                                                                                               |
|---------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| Python structural / governance config | `analyze` → `start` → `get_relevant_memory` → edit → `analyze` → memory write if required → `finish(after_run_id=...)` |
| Documentation-only / non-Python       | `analyze` → `start` → `get_relevant_memory` → edit → memory write if required → `finish(changed_files=[...])`          |
| Blocked follow-up                     | queue behind foreign active intent, then promote before editing                                                        |
| Read-only / spec validation           | no edit workflow unless repository files change                                                                        |

Do not skip, replace, reorder, or approximate required steps. Optional/profile-dependent steps may be skipped only under
their stated conditions. If a required MCP call fails or is unavailable, stop and report the blocker instead of
continuing as a normal edit.

### Before editing

1. `analyze_repository(root="<abs_path>")`
    - Skip only when a valid recent run for the same absolute root already exists.
2. `start_controlled_change(root="<abs_path>", scope={...}, intent="...")`
    - Returns blast radius, budget, workspace state, and `intent_id`.
    - If `status: "needs_analysis"`, run `analyze_repository` first.
    - If `status: "queued"`, do not edit; wait for promotion.
    - If `concurrent_intents` is non-empty without queue, narrow scope or ask.
    - If start blocks only because declared scope is already dirty and this is resumed known WIP with no foreign
      overlap, retry with `dirty_scope_policy="continue_own_wip"`; finish must still prove scope.
3. Edit only after `status == "active"` and `edit_allowed == true`.
4. `get_relevant_memory(root="<abs_path>", scope=... or intent_id=...)`
    - `root` is required; `intent_id` alone fails MCP validation.
5. Edit within declared scope only.

### After editing

1. Run `analyze_repository(root="<abs_path>")` after edits for Python structural and governance config changes.
    - Required after-run must have a new `run_id`; identical before/after runs fail Python structural verification with
      `after_run_not_new`.
    - May be skipped for documentation-only and other non-Python patches when `finish` can verify from changed-file
      evidence.
2. Before finish, perform mandatory incident/complexity/decision memory check.
3. Call `finish_controlled_change(intent_id=..., changed_files=[...], after_run_id=...)`.
    - Returns scope check, verification, receipt, and clears accepted intents.
    - `auto_clear=true` by default; intent clears only on accepted outcomes.
    - If `status: "unverified"`, the intent stays active. Follow `next_step`, then call `finish` again on the same
      `intent_id` with missing evidence.
    - If `status: "violated"`, the intent stays active. Remove out-of-scope changes and retry `finish`, or expand scope
      via `start_controlled_change`.
    - If `user_action_required: true`, stop and escalate.

### Finish evidence reconciliation

`finish` reconciles evidence with the start-time dirty snapshot and the full git tree.

Blocking reasons:

- under-reported in-scope dirty → `finish_block_reason: missing_evidence`
- live foreign in-scope overlap → `foreign_dirty_overlap`
- unattributed out-of-scope dirt blocks only when `CODECLONE_STRICT_FINISH` is truthy → `own_unscoped_dirty`

Advisory/non-blocking cases:

- new/modified/unknown unattributed out-of-scope dirt and unchanged preexisting unscoped dirty are advisory unless
  strict finish applies; finish may return `accepted_with_external_changes`
- foreign active/stale dirty outside scope → `foreign_attributed_outside_scope` and is ignored
- recoverable/dead-PID intents do not grant foreign attribution

If `reason=workspace_hygiene`, read `finish_block_reason`; do not bypass with atomic verify. Advisory hygiene fields
such as `new_unattributed_unscoped_dirty` may appear in `external_changes` or `accepted_with_external_changes` but are
not block reasons.

## Engineering Memory

Engineering Memory is a local SQLite store of evidence-linked repository facts. MCP help:
`help(topic="engineering_memory")`. Published contract pages are TBD during docs-site migration; verify behavior against
code and tests.

**Chat is not memory.** Conversation text is ephemeral across context shrink, new sessions, and new MCP processes.
Durable facts the next agent must know belong in Engineering Memory via MCP, not only in chat or compact summaries.

### Bootstrap

Default `mcp_sync_policy=bootstrap_if_missing` auto-creates the store from the latest MCP run on `get_relevant_memory`.

Explicit refresh: `manage_engineering_memory(action="refresh_from_run")`.

CLI `memory init` remains for CI/offline. Human approval is still required for agent drafts through the VS Code Memory
view, not MCP and not `codeclone memory approve`.

### Read memory after start

After `start_controlled_change` returns `edit_allowed: true`:

1. Call `get_relevant_memory(root="<abs_path>", scope=... or intent_id=...)`.
2. Read contract warnings, stale decisions, and `contradiction_note` alerts.
3. Use `query_engineering_memory(mode=for_path)` or `mode=search` for drill-down.
4. Do not ignore stale memory warnings.
5. Do not treat `draft`, `inferred`, or excluded stale records as established facts.
6. If memory contains a `contradiction_note` for scope, surface it to the user before editing.

### Memory scope and token hygiene

- Never use project root as memory scope.
- Compress `record_candidate` statements to one durable fact: target ≤300 chars; `validate_claims` warns above 500; hard
  limit 1000.
- List responses default to compact previews.
- Treat `records[]`, `experiences[]`, and `trajectories[]` as separate evidence lanes:
    - `records` = asserted knowledge
    - `trajectories` = episodic workflow evidence
    - `experiences` = advisory patterns
    - `coverage` = visibility metadata
- Scores are lane-local. Never compare `relevance_score` across lanes.
- `for_path` and plain non-semantic search are unranked.
- `subject_count` / `subjects_truncated` means more subjects exist, not that evidence disappeared.
- Use `mode=get` or `detail_level=full` for complete subjects, agent facets, trajectory contracts, steps, evidence ids,
  and payloads.
- `patch_trail_summary` rides each trajectory and is never duplicated at the payload root.

### Mandatory memory write before finish

Do not call `finish_controlled_change` after a non-trivial edit cycle until this check passes.

Write at least one durable MCP note before finish if any trigger fired:

| Trigger    | Examples                                                                                                     |
|------------|--------------------------------------------------------------------------------------------------------------|
| Incident   | verify/hygiene surprise, `unverified`/`violated` recovery, workaround, blocked step, foreign intent friction |
| Complexity | non-obvious root cause, multi-file debug, near `do_not_touch`, acted on stale/contradiction memory           |
| Decision   | tradeoff, integration quirk, “next agent must not repeat X”                                                  |

Skip only trivial edits: typo, one obvious line, nothing to relearn.

Write through MCP only:

```text
manage_engineering_memory(
  root="<abs_path>",
  action=record_candidate,
  record_type=risk_note | change_rationale,
  statement="<what happened, what we learned, what to do next time>",
  subject_path="<main repo-relative file you touched>"
)
```

Other allowed memory writes:

| Timing                          | Tool                                                                           |
|---------------------------------|--------------------------------------------------------------------------------|
| During edit, stable observation | `record_candidate`                                                             |
| Before finish, batch notes      | `finish_controlled_change(..., propose_memory=true)`                           |
| Optional pre-finish claim check | `manage_engineering_memory(action=validate_claims, text=...)` on `claims_text` |
| After accepted patch            | `finish(..., propose_memory=true)` → `memory_candidates`                       |

Agents cannot call `approve`, `reject`, or `archive` via MCP. Ask the user to promote drafts in the CodeClone VS Code
Memory view.

Memory cannot authorize edits, expand scope, or override findings.

## Queue / promote workflow

When `start` returns `status: "queued"`:

1. `start_controlled_change(on_conflict="queue")` → `status: "queued"`.
2. Wait for the foreign intent to clear.
3. `manage_change_intent(action="promote", intent_id=...)`.
4. Edit only after promote returns `status: "active"`.
5. If `before_run_evicted`, re-analyze and re-start.

Live foreign intent means stop, not kill. Never suggest killing a process without explicit user confirmation that the
PID is abandoned.

## Atomic workflow fallback

When `start_controlled_change` / `finish_controlled_change` are unavailable, use the atomic path in the change-control
skill.

Rules:

- Prefer `start_controlled_change` / `finish_controlled_change`.
- Use atomic tools only for queue/promote/recover or when workflow tools are unavailable.
- Do not mix workflow and atomic verification paths in one edit cycle.
- Queue/promote/recover via `manage_change_intent` may be used alongside workflow tools because workflow tools do not
  expose those administrative transitions.

## Required rules

- `start_controlled_change` does not run analysis; ensure a valid run exists before calling it.
- `finish_controlled_change` does not run analysis; for Python structural and governance config changes, run
  `analyze_repository` after editing and pass `after_run_id`.
- MUST NOT edit files without declaring intent first, including `tests/**/*.py`.
- MUST NOT edit unless `start_controlled_change` returned `status == "active"` and `edit_allowed == true`.
- MUST NOT edit while intent is `queued`; promote first.
- MUST NOT silently expand scope. If files outside declared scope are needed, stop before editing them. Expand only
  after user approval unless the user already explicitly allowed expansion. Call `start_controlled_change` again with
  expanded scope and continue only when the expanded intent is active.
- Do not edit extra files based on blast-radius context alone.
- `do_not_touch` is a hard boundary. `review_context` is context, not a ban.
- Do not update baselines, analysis cache, or generated reports.
- When `finish` or verify returns `next_step`, follow it.
- CodeClone findings are the source of truth; do not reinterpret.
- If `finish_controlled_change` returns `status: "unverified"` or `"violated"`, do not claim verification.
- Leaving an active or recoverable own intent behind is blocked cleanup, not completion.
- MUST NOT call `finish_controlled_change` after a non-trivial cycle without `record_candidate` or `propose_memory=true`
  when incident/complexity/decision triggers applied.
- MUST NOT treat assistant chat text as Engineering Memory.

## User escalation policy

Run routine controller steps automatically. Queue blocked follow-up work automatically when it can wait; do not ask
before queueing.

Ask the user only when:

- scope expansion is required and was not already explicitly allowed
- a `do_not_touch` path must be touched
- live foreign intent overlaps and queue is not appropriate
- patch contract returned `violated`
- patch contract returned `unverified` and the deterministic `next_step` cannot be executed
- baseline, analysis cache, canonical reports, or generated state would be modified
- recovery or reset of another agent’s intent is needed

Routine controller work is automatic. Boundary decisions require the user.

Workflow `status: "blocked"` is not persisted registry lifecycle; clear abandoned blocked intents via
`manage_change_intent(action="clear")`.

## Completion gate

Do not say “done”, “implemented”, “validated”, “verified”, “ready”, or equivalents unless all conditions hold:

1. `finish_controlled_change` returned `status: "accepted"` or `"accepted_with_external_changes"`; or, in atomic
   fallback, `manage_change_intent(action="check")` returned `clean` or `expanded`,
   `check_patch_contract(mode="verify")` returned `accepted`, and `manage_change_intent(action="clear")` succeeded.
2. `scope_check.status` is `"clean"` or `"expanded"`.
3. `intent_cleared` is `true`; or atomic `manage_change_intent(action="clear")` succeeded.
4. If `claims` is present and `claims.valid` is `false`, report the warnings.
5. Claim validation was handled by `finish_controlled_change` when `review_text` was provided and
   `claim_validation_recommended` was `true`; for atomic workflow, final summary claims passed `validate_review_claims`
   with `patch_health_delta` from verify unless `claim_validation_recommended` was explicitly `false`.

If status is `accepted_with_external_changes`, report the external-change advisory instead of presenting the patch as
fully clean.

If any item cannot be completed, report `BLOCKED` or `UNVERIFIED`, include `intent_id`, and state the exact missing
step.

## Verification profiles

The controller derives verification profile from actual changed files. The agent does not choose or claim the profile.
`finish_controlled_change` computes it through `check_patch_contract(mode="verify")`; atomic workflow calls
`check_patch_contract(mode="verify")` directly.

| Profile                 | When                                                                                         | `after_run` required | Structural checks |
|-------------------------|----------------------------------------------------------------------------------------------|---------------------:|-------------------|
| `python_structural`     | any `.py` / `.pyi` touched                                                                   |                  yes | all               |
| `governance_config`     | config files only: `pyproject.toml`, CI, Dockerfile, etc.                                    |                  yes | not applicable    |
| `documentation_only`    | only docs files: `.md`, `.rst`, `LICENSE`, etc.                                              |                   no | not applicable    |
| `non_python_patch`      | other files, no Python/docs                                                                  |                   no | not applicable    |
| `state_artifact_change` | CodeClone state artifacts: `codeclone.baseline.json`, `.codeclone/**`, `.cache/codeclone/**` |         no; violated | not applicable    |

Rules:

- `start` is always required before edits; lighter profiles affect after-run/verify only.
- If any Python source, governance configuration, baseline, cache, or generated state file was touched, lightweight path
  is not accepted.
- Documentation-only patches can verify without `after_run_id` when `changed_files` or `diff_ref` evidence is provided.
- Other non-Python patches may verify without `after_run_id`, but only with controller-reported limitations; do not
  present as full structural verification.
- Receipts use “not applicable” for skipped structural checks, never “passed”.
- Claim Guard may reject or warn on claims that exceed the derived profile.
- For documentation-only patches, “no Python files touched” is allowed; “no structural regressions” requires structural
  evidence from an after-run.
- `novelty="known"` is baseline-relative, not patch-relative. Do not infer that a patch did not introduce/reintroduce a
  finding from baseline novelty alone; patch-local regression claims require clean before-run to after-run evidence.

## When to skip edit workflow

- Read-only tasks: analysis, validation, research
- User explicitly says analysis-only
- CodeClone MCP is unavailable and the task is read-only
- For repository edits that require change control when CodeClone MCP is unavailable, stop and report the blocker

## Spec writing discipline

Specs are disposable implementation briefs, not documentation. They are deleted after implementation and validation.

Invariants:

- **One model per decision.** Choose one approach and close alternatives; never leave incompatible paths in one section.
- **Verify against code.** Verify every function signature, data model, and behavior claim against current source before
  writing.
- **No aspirational APIs.** If a function does not exist yet, say so; do not describe it as existing.
- **Decision table for state machines.** Exhaustively map every input combination to exactly one output.
- **Dependency direction explicit.** List imports for each new file and what imports it; verify against `AGENTS.md` §14.

Self-check before delivery:

1. Conflicting approaches? Pick one.
2. Code snippets match actual APIs? Read source.
3. State transitions deterministic? Write decision table.
4. Implementer can follow without ambiguity? If unclear, it is wrong.

## Validation discipline

When validating implementation against a spec:

1. Read all implementation files, not just grep results.
2. Cross-reference every spec requirement against code.
3. Run relevant tests: `uv run pytest -q <test_files>`.
4. Run `uv run pre-commit run --all-files` if the user asks to commit.
5. Check MCP tool visibility if a new tool was added.
6. Report `conformant` / `improved` / `divergent` / `missing` with evidence.

## Verification commands

```bash
# Always
uv run pre-commit run --all-files

# MCP changes
uv run pytest -q tests/test_mcp_service.py tests/test_mcp_server.py

# Full suite
uv run pytest -q
```

See `AGENTS.md` §3 for surface-specific commands.

## Hard boundaries

- Never update golden snapshots merely to “fix” tests; snapshot updates require explicit user approval and a
  contract/schema change rationale.
- Never change fingerprint semantics without `BASELINE_FINGERPRINT_VERSION` review.
- Never make base `codeclone` depend on MCP runtime packages.
- Never let MCP mutate baselines, source files, canonical reports, or analysis cache.
- Ephemeral coordination state (workspace intents) and audit trail under `.codeclone/` are allowed only through
  controller and audit contracts.
- Never iterate sets/dicts without sorting when output order matters.
- Never introduce `Any` in core/domain code without immediately narrowing it.
- Never create `*.md` specs inside `docs/`; use `specs/`.
- Version constants live in `codeclone/contracts/__init__.py`; always read from there, never copy from another doc.

## Compact instructions

When compacting, preserve only task-critical state.

### Universal

- current task goal and explicit non-goals
- modified files and why each was modified
- passing/failing test commands and exact remaining failures
- user corrections and rejected approaches, including rejection reasons
- unresolved blockers and next safe action

### Change-control state: highest priority

- active intent: `intent_id`, lifecycle status (`active` / `queued` / `unverified` / `violated` / `recoverable`),
  declared scope, `edit_allowed`, before/after `run_id`s
- expected verification profile (`python_structural` / `governance_config` / `documentation_only` / `non_python_patch`)
  and whether `after_run_id` is still required
- finish outcome: `accepted` / `accepted_with_external_changes` / `BLOCKED` / `UNVERIFIED`; if not accepted, exact
  missing step
- foreign intents or queue position currently blocking work
- pending MCP memory writes: incident/complexity/decision triggers that fired but have not yet been recorded with
  `record_candidate` or `propose_memory=true`

### Contracts

Preserve whether the current task touches a versioned contract, especially `codeclone/contracts/__init__.py` or
`BASELINE_FINGERPRINT_VERSION`, and that it must not change without review. Do not preserve the full contract list; it
lives in code.

### Do not preserve

- full logs when failure summaries are enough
- repeated explanations
- obsolete failed attempts unless they explain a current constraint

Compact summaries are still ephemeral. Durable facts, including rejected approaches the next agent must not repeat, must
be written to Engineering Memory through MCP.

## Commit style

```text
feat(scope): short imperative description

Optional body with context.
```

Scopes: `mcp`, `cli`, `core`, `baseline`, `cache`, `report`, `html`, `metrics`, `memory`, `observability`, `analytics`,
`docs`, `vscode`, `codex`, `claude-desktop`, `claude-code`, `cursor`.

Prefixes: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.
