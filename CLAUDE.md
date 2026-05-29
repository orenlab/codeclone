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
Creating or editing a spec is also a repository edit. "Spec only" is not a
reason to skip change control.

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

Do not skip, replace, reorder, or approximate these steps. If a required MCP
call fails or is unavailable, stop and report the blocker instead of
continuing as a normal edit.

Before editing any repository files:

1. `manage_change_intent(action="list_workspace", root="<abs_path>")`
   — if `foreign_active` intents overlap, do not edit. Prefer
   `on_conflict="queue"` in step 3 for follow-up work that can wait.
   Ask the user only if you need to edit immediately, recover/reset
   another agent's intent, or touch a `do_not_touch` path
2. `analyze_repository(root="<abs_path>")`
3. `manage_change_intent(action="declare", scope={...})`
   — if `concurrent_intents` non-empty, narrow scope or ask.
   Use `on_conflict="queue"` to create a queued intent behind foreign
   active intents instead of failing. A queued intent does not own scope
   and cannot be verified — promote it first (step 3b)
   3b. *(only for queued intents)* When the foreign intent clears:
   `manage_change_intent(action="promote", intent_id=...)`
   — transitions queued → active, pins the run, renews the lease.
   If the before-run was evicted, re-analyze and redeclare
4. `get_blast_radius(files=[...])`
5. `check_patch_contract(mode="budget")`
6. Edit within declared scope only
7. `analyze_repository(root="<abs_path>")` — re-run after edits for Python
   structural and governance config changes. For documentation-only or
   non-Python patches, this step may be skipped; the controller derives the
   profile from actual changed files during verify. If unsure, re-run
8. `manage_change_intent(action="check", intent_id=..., changed_files=[...])`
   — pass the original `intent_id` explicitly and provide either
   `changed_files` or `diff_ref` (the intent is bound to the before-run;
   without `intent_id`, `_resolve_intent` looks up the latest run and
   misses it)
9. `check_patch_contract(mode="verify", after_run_id=..., intent_id=...)`
   — `before_run_id` auto-resolves from intent when omitted.
   `after_run_id` is required only when the derived verification profile
   requires it (`python_structural`, `governance_config`). For
   `documentation_only` and `non_python_patch`, pass `changed_files` or
   `diff_ref` evidence and omit `after_run_id`.
   Non-accepted responses include `next_step` hint — follow it.
   Verify compares the intent's `report_digest` against the before-run;
   redeclare on the after-run would cause an `expired` mismatch
10. `manage_change_intent(action="clear", intent_id=...)`

### Rules

- MUST NOT edit files without declaring intent first.
- MUST NOT silently expand scope — redeclare with expanded scope before
  editing the extra file.
- MUST NOT redeclare on the after-run. Re-declare only to expand scope before
  editing or to start a separate change.
- MUST NOT call the `check` action without exactly one changed-scope source:
  `changed_files` or `diff_ref`.
- MUST clear the original intent by explicit `intent_id` after successful
  verification.
- After re-analyze, pass `intent_id` explicitly to
  `check`/`get`/`verify` — otherwise `_resolve_intent` resolves by
  latest run_id and misses intents bound to the before-run.
- `do_not_touch` is a hard boundary. `review_context` is context, not a ban.
- Do not update baselines, analysis cache, or generated reports.
- If `list_workspace` shows overlapping foreign intent, stop and coordinate —
  or use `on_conflict="queue"` to queue behind it.
- MUST NOT edit while intent is `queued`. Promote first.
- MUST NOT call verify on a queued intent — verify rejects with
  `reason="intent_not_active"`.
- MAY call budget on a queued intent for planning only. Budget responses
  for queued intents include `edit_allowed=false` and are not edit
  permission.
- When verify returns a `next_step` hint, follow it — do not invent a
  different recovery path.
- CodeClone findings are the source of truth — do not reinterpret.
- If `check_patch_contract(mode="verify")` returns `unverified` or `violated`,
  do not claim the patch is verified.
- Leaving an active or recoverable own intent behind is a blocked cleanup, not
  a completed task.
- Live foreign intent means **stop**, not kill. Never suggest killing
  a process without explicit user confirmation that the PID is abandoned.

### User escalation policy

Run routine controller steps automatically. Queue blocked follow-up work
automatically when it can wait — do not ask before queueing.

Ask the user only when:

- scope expansion is required;
- a `do_not_touch` path must be touched;
- a live foreign intent overlaps and queue is not appropriate;
- patch contract returned `violated` or `unverified`;
- baseline, cache, or generated state would be modified;
- recovery or reset of another agent's intent is needed.

Routine controller work is automatic. Boundary decisions require the user.

### Completion gate

Do not say "done", "implemented", "validated", "verified", "ready", or
equivalent unless all of these are true:

1. either:
    - an after-run was created after the last edit (required for
      `python_structural` and `governance_config` patches); or
    - `check_patch_contract(mode="verify")` derived a profile that does not
      require `after_run_id` (`documentation_only` or `non_python_patch`);
2. `manage_change_intent(action="check", intent_id=..., changed_files=...)`
   or `diff_ref=...` returned `clean`;
3. `check_patch_contract(mode="verify", intent_id=..., after_run_id=...)`
   returned `accepted`; `after_run_id` is required only when the derived
   verification profile requires it;
4. any final summary claims passed `validate_review_claims` — skip only
   when `claim_validation_recommended` is explicitly `false` in the
   controller response, not by agent judgment;
5. `manage_change_intent(action="clear", intent_id=...)` succeeded.

If any item cannot be completed, report `BLOCKED` or `UNVERIFIED`, include the
`intent_id`, and state the exact missing step. Do not present the work as
finished.

### Verification profiles

The controller derives a **verification profile** from actual changed files.
The profile determines which structural checks apply. The agent does not choose
the profile — it is computed by `check_patch_contract(mode="verify")`.

| Profile                 | When                                                | `after_run` required | Structural checks |
|-------------------------|-----------------------------------------------------|----------------------|-------------------|
| `python_structural`     | any `.py` / `.pyi` touched                          | yes                  | all               |
| `governance_config`     | config files only (pyproject.toml, CI, Dockerfile…) | yes                  | not applicable    |
| `documentation_only`    | only docs files (`.md`, `.rst`, LICENSE…)           | no                   | not applicable    |
| `non_python_patch`      | other files, no Python / docs                       | no                   | not applicable    |
| `state_artifact_change` | baseline or cache touched                           | no (violated)        | not applicable    |

Key rules:

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
