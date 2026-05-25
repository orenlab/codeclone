# CodeClone — Claude Code Directives

## Identity

CodeClone: deterministic structural controller for Python.
Full architecture, contracts, and agent playbook → `AGENTS.md`.
Code is the source of truth. If docs and code diverge, follow code.

## Default role

**Specs and validation only.** Do not edit production code unless the
user explicitly permits it for a specific task. "Реализуй" / "Implement"
is explicit permission. "Проверь" / "Validate" is not.

When permitted to edit code, follow the change control workflow below.

## Change control workflow

This workflow is mandatory protocol, not advisory text. Do not skip, replace,
reorder, or approximate these steps. If a required MCP call fails or is
unavailable, stop and report the blocker instead of continuing as a normal
edit.

Before editing any repository files:

1. `manage_change_intent(action="list_workspace", root="<abs_path>")`
   — if `foreign_active` intents overlap, **stop and ask the user**
2. `analyze_repository(root="<abs_path>")`
3. `manage_change_intent(action="declare", scope={...})`
   — if `concurrent_intents` non-empty, narrow scope or ask
4. `get_blast_radius(files=[...])`
5. `check_patch_contract(mode="budget")`
6. Edit within declared scope only
7. `analyze_repository(root="<abs_path>")` — re-run after edits
8. `manage_change_intent(action="check", intent_id=..., changed_files=[...])`
   — pass the original `intent_id` explicitly and provide either
   `changed_files` or `diff_ref` (the intent is bound to the before-run;
   without `intent_id`, `_resolve_intent` looks up the latest run and
   misses it)
9. `check_patch_contract(mode="verify", before_run_id=...,
   after_run_id=..., intent_id=...)` — verify compares the intent's
   `report_digest` against the before-run; redeclare on the after-run
   would cause an `expired` mismatch
10. `manage_change_intent(action="clear")`

### Rules

- MUST NOT edit files without declaring intent first.
- MUST NOT silently expand scope — redeclare with expanded scope before
  editing the extra file.
- MUST NOT redeclare on the after-run. Re-declare only to expand scope before
  editing or to start a separate change.
- MUST NOT call the `check` action without exactly one changed-scope source:
  `changed_files` or `diff_ref`.
- After re-analyze, pass `intent_id` explicitly to
  `check`/`get`/`verify` — otherwise `_resolve_intent` resolves by
  latest run_id and misses intents bound to the before-run.
- `do_not_touch` is a hard boundary. `review_context` is context, not a ban.
- Do not update baselines, cache, or generated reports.
- If `list_workspace` shows overlapping foreign intent, stop and coordinate.
- CodeClone findings are the source of truth — do not reinterpret.
- If `check_patch_contract(mode="verify")` returns `unverified` or `violated`,
  do not claim the patch is verified.
- Live foreign intent means **stop**, not kill. Never suggest killing
  a process without explicit user confirmation that the PID is abandoned.

### When to skip

- Read-only tasks (analysis, validation, research)
- CodeClone MCP not available
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

- Never update golden snapshots to "fix" tests.
- Never change fingerprint semantics without `FINGERPRINT_VERSION` review.
- Never make base `codeclone` depend on MCP runtime packages.
- Never let MCP mutate baselines, source files, reports, or cache.
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
