# CodeClone — Claude Code Directives

## Identity

CodeClone: deterministic structural controller for Python.
Full architecture, contracts, and agent playbook → `AGENTS.md`.
Code is the implementation source of truth. If docs and code diverge,
follow code for implementation decisions and report the divergence.

## Default role

**Specs and validation only.** Do not edit production code unless the
user explicitly permits it for a specific task. "Реализуй" / "Implement"
is explicit permission. "Проверь" / "Validate" is not.

When permitted to edit code, follow the change control workflow below.
Applies to any tracked file in the target repository. Task type (coverage, CI,
docs-only) does not skip `start`. Spec edits count too. When CodeClone MCP is
available, read the bundled **`codeclone-change-control`** skill for the full
pipeline (tool tiers, decision tables, profiles).

## Change control workflow

The protocol below is mandatory, but the visible workflow depends on the
patch type:

- **Python structural / governance config**: full before/after workflow.
- **Documentation-only**: lightweight verify; no after-run required when the
  controller derives `documentation_only`.
- **Blocked follow-up**: queue intent behind foreign active; promote before
  editing.
- **Read-only / spec validation**: no edit workflow unless repository files
  change.

Do not skip, replace, reorder, or approximate the required steps for the
derived workflow profile. Steps explicitly marked as optional or
profile-dependent may be skipped only under the stated conditions.
If a required MCP call fails or is unavailable, stop and report the blocker
instead of continuing as a normal edit.

Before editing any repository files:

1. `analyze_repository(root="<abs_path>")`
   — if a valid recent run for the same absolute root already exists, skip
2. `start_controlled_change(root="<abs_path>", scope={...}, intent="...")`
   — returns blast radius, budget, workspace state, intent_id
   — if `status: "needs_analysis"`, run `analyze_repository` first
   — if `status: "queued"`, do not edit; wait for promotion
   — if `concurrent_intents` non-empty without queue, narrow scope or ask
3. Edit within declared scope only
4. `analyze_repository(root="<abs_path>")`
   — after-run; required for Python structural and governance config changes.
   May be skipped for documentation-only and other non-Python patches when
   `finish` can verify from changed-file evidence
5. `finish_controlled_change(intent_id=..., changed_files=[...], after_run_id=...)`
   — returns scope check, verification, receipt, and clears intent
   — if `status: "unverified"`, the intent stays active; follow `next_step`
   (e.g., run `analyze_repository`), then call `finish` again on the
   **same `intent_id`** with the missing evidence
   — if `status: "violated"` (scope), the intent stays active; either
   remove out-of-scope changes and retry `finish`, or expand scope via
   `start_controlled_change` with a wider scope
   — if `user_action_required: true`, stop and escalate to the user
   — `auto_clear=true` by default; intent cleared only on accepted

Workflow profiles determine which steps are needed:

- **Python structural / governance config**:
  `analyze` → `start` → edit → `analyze` → `finish(after_run_id=...)`
- **Documentation-only / non-Python**:
  `analyze` → `start` → edit → `finish(changed_files=[...])`
  For `non_python_patch`, report controller-stated limitations and do not
  present the result as full structural verification.

Queue/promote workflow (when `start` returns `status: "queued"`):

1. `start_controlled_change(on_conflict="queue")` → `status: "queued"`
2. Wait for foreign intent to clear
3. `manage_change_intent(action="promote", intent_id=...)`
   — edit only after promote returns `status: "active"`
   — if `before_run_evicted`: re-analyze and re-start

### Atomic workflow (fallback)

When `start_controlled_change` / `finish_controlled_change` are unavailable,
use the atomic path in the change-control skill. Do not mix primary and atomic
verification in one cycle.

### Rules

- Prefer `start_controlled_change` / `finish_controlled_change` over
  the atomic workflow. Use atomic tools only for queue/promote/recover
  or when the workflow tools are unavailable.
- Do not mix workflow and atomic verification paths in the same edit
  cycle. Queue/promote/recover operations via `manage_change_intent`
  are allowed alongside workflow tools because workflow tools do not
  expose those administrative transitions.
- `start_controlled_change` does not run analysis. Ensure a valid run
  exists before calling it.
- `finish_controlled_change` does not run analysis. For Python
  structural and governance config changes, run `analyze_repository`
  after editing and pass `after_run_id`.
- MUST NOT edit files without declaring intent first — including `tests/**/*.py`.
- MUST NOT silently expand scope. If the fix requires files outside the
  declared scope, stop before editing them. Expand scope only after user
  approval unless the user already explicitly allowed expansion. Call
  `start_controlled_change` again with the expanded scope to get a fresh
  intent with updated blast radius and budget. Continue only when the
  expanded intent is active. Do not edit extra files based on blast-radius
  context alone.
- MUST NOT edit while intent is `queued`. Promote first.
- `do_not_touch` is a hard boundary. `review_context` is context, not a ban.
- Do not update baselines, analysis cache, or generated reports.
- When `finish` or verify returns a `next_step` hint, follow it — do not
  invent a different recovery path.
- CodeClone findings are the source of truth — do not reinterpret.
- If `finish_controlled_change` returns `status: "unverified"` or
  `"violated"`, do not claim the patch is verified.
- Leaving an active or recoverable own intent behind is a blocked cleanup, not
  a completed task.
- Live foreign intent means **stop**, not kill. Never suggest killing
  a process without explicit user confirmation that the PID is abandoned.

### User escalation policy

Run routine controller steps automatically. Queue blocked follow-up work
automatically when it can wait — do not ask before queueing.

Ask the user only when:

- scope expansion is required and was not already explicitly allowed by
  the user;
- a `do_not_touch` path must be touched;
- a live foreign intent overlaps and queue is not appropriate;
- patch contract returned `violated`, or returned `unverified` and the
  agent cannot execute the deterministic `next_step`;
- baseline, analysis cache, canonical reports, or generated state would
  be modified;
- recovery or reset of another agent's intent is needed.

Routine controller work is automatic. Boundary decisions require the user.

### Completion gate

Do not say "done", "implemented", "validated", "verified", "ready", or
equivalent unless all of these are true:

1. `finish_controlled_change` returned `status: "accepted"` (or
   `"accepted_with_external_changes"`); OR, in the atomic fallback
   workflow, `manage_change_intent(action="check")` returned `clean` or
   `expanded`, `check_patch_contract(mode="verify")` returned `accepted`,
   and `manage_change_intent(action="clear")` succeeded;
2. `scope_check.status` is `"clean"` or `"expanded"`;
3. `intent_cleared` is `true` in the finish response; OR
   `manage_change_intent(action="clear")` succeeded;
4. if `claims` is present in the finish response and `claims.valid` is
   `false`, report the warnings — do not suppress;
5. claim validation was handled by `finish_controlled_change` when
   `review_text` was provided and `claim_validation_recommended` was
   `true`; for atomic workflow, final summary claims passed
   `validate_review_claims` unless `claim_validation_recommended` was
   explicitly `false`.

If status is `accepted_with_external_changes`, report the external-change
advisory instead of presenting the patch as fully clean.

If any item cannot be completed, report `BLOCKED` or `UNVERIFIED`, include the
`intent_id`, and state the exact missing step. Do not present the work as
finished.

### Verification profiles

The controller derives a **verification profile** from actual changed files.
The profile determines which structural checks apply. The agent does not choose
the profile — it is computed by `finish_controlled_change` (through
`check_patch_contract(mode="verify")` internally), or directly by
`check_patch_contract(mode="verify")` in the atomic workflow.

| Profile                 | When                                                | `after_run` required | Structural checks |
|-------------------------|-----------------------------------------------------|----------------------|-------------------|
| `python_structural`     | any `.py` / `.pyi` touched                          | yes                  | all               |
| `governance_config`     | config files only (pyproject.toml, CI, Dockerfile…) | yes                  | not applicable    |
| `documentation_only`    | only docs files (`.md`, `.rst`, LICENSE…)           | no                   | not applicable    |
| `non_python_patch`      | other files, no Python / docs                       | no                   | not applicable    |
| `state_artifact_change` | baseline or cache touched                           | no (violated)        | not applicable    |

Key rules:

- **`start` is always required** before edit; lighter profiles only affect
  after-run / verify, not intent declaration.
- If **any** Python source, governance configuration, baseline, cache, or
  generated state files were touched, the lightweight path is not accepted.
- Documentation-only patches can verify without `after_run_id`
  when `changed_files` or `diff_ref` evidence is provided.
- Other non-Python patches may verify without `after_run_id`, but only
  with controller-reported limitations. Do not present this as full
  structural verification.
- The agent MUST NOT claim which profile applies — CodeClone decides.
- Receipts use "not applicable" for skipped structural checks, never "passed".
- Claim Guard may reject or warn on claims that exceed the derived profile.
  For documentation-only patches, "no Python files touched" is allowed;
  "no structural regressions" requires structural evidence from an after-run.

### When to skip

- Read-only tasks (analysis, validation, research)
- CodeClone MCP not available and the task is read-only. For repository
  edits that require change control, stop and report the blocker
- User explicitly says analysis-only

## Spec writing discipline

Specs are disposable implementation briefs, not documentation.
They are deleted after implementation and validation.

### Invariants

- **One model per decision.** If the spec describes alternative
  approaches, choose one and close the others. Never leave two
  incompatible paths in the same section.
- **Verify against code.** Every function signature, data model, and
  behavior claim in the spec must be verified against current code
  before writing. Read the source, do not assume.
- **No aspirational APIs.** If a function doesn't exist yet, say so.
  Do not describe it as if it does.
- **Decision table for state machines.** If the spec introduces states
  or classifications, provide an exhaustive decision table. Every
  input combination must map to exactly one output.
- **Dependency direction explicit.** List what each new file imports
  and what imports it. Verify against the architecture rules in
  `AGENTS.md` §14.

### Self-check before delivery

Before presenting a spec, verify:

1. Are there two conflicting approaches in the same spec? → pick one.
2. Does every code snippet match the actual codebase API? → read source.
3. Is every state transition deterministic? → write the decision table.
4. Can the implementer follow this without interpreting ambiguity? → if
   unclear, it's wrong.

## Validation discipline

When validating an implementation against a spec:

1. Read all implementation files (not just grep).
2. Cross-reference every spec requirement against code.
3. Run the relevant tests: `uv run pytest -q <test_files>`.
4. Run `uv run pre-commit run --all-files` if the user asks to commit.
5. Check MCP tool visibility if a new tool was added.
6. Report: conformant / improved / divergent / missing — with evidence.

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

- Never update golden snapshots merely to "fix" tests. Snapshot updates
  require explicit user approval and a contract/schema change rationale.
- Never change fingerprint semantics without `FINGERPRINT_VERSION` review.
- Never make base `codeclone` depend on MCP runtime packages.
- Never let MCP mutate baselines, source files, canonical reports, or
  analysis cache. Ephemeral coordination state (workspace intents) and
  audit trail under `.cache/codeclone/` are allowed only through the
  controller and audit contracts.
- Never iterate sets/dicts without sorting when output order matters.
- Never introduce `Any` in core/domain code without narrowing it immediately.
- Never create `*.md` specs inside `docs/` — use `specs/` directory.
- Version constants live in `codeclone/contracts/__init__.py` — always
  read from there, never copy from another doc.

## Commit style

```
feat(scope): short imperative description

Optional body with context.
```

Scopes: `mcp`, `cli`, `core`, `baseline`, `cache`, `report`, `html`,
`metrics`, `docs`, `vscode`, `codex`, `claude-desktop`.
Prefixes: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.
