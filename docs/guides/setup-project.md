---
title: "Set up a project"
audience: public
doc_type: guide
status: published
source_commit: "60eac9c367d74deeba1478521461addfedd8e681"
---

## What it is

`codeclone setup apply` initializes CodeClone governance configuration. When you confirm, it writes exactly two files:

- Merges the `[tool.codeclone]` section into your `pyproject.toml`
- Appends CodeClone cache/state paths to `.gitignore`

It does **not** create a baseline snapshot, audit database, or intent registry — those artifacts are produced later, on demand, by analysis (`codeclone . --update-baseline`) and controlled-change runs. `setup status`, `setup doctor`, and `setup plan` are read-only; only `setup apply` writes, and only after explicit confirmation.

## When to use it

Run setup when:

- Initializing CodeClone in a new project
- Re-establishing governance after a reset
- Applying a reviewed plan to the filesystem

Do **not** run setup if another engineer is actively using CodeClone on the same project (governance intent conflicts will block execution).

## Basic workflow

```mermaid
sequenceDiagram
  actor User
  User->>setup plan: codeclone setup plan
  User->>preview: Review output
  User->>setup apply: codeclone setup apply --yes --plan-id <id>
  setup apply->>filesystem: Merge [tool.codeclone] into pyproject.toml + append .gitignore
  setup apply-->>User: status=accepted
```

## Key commands

| Command | Purpose | Flags |
|---------|---------|-------|
| `codeclone setup plan` | Preview all proposed changes | (none required) |
| `codeclone setup apply --dry-run` | Simulate execution without writing | `--dry-run` |
| `codeclone setup apply --yes` | Execute interactively or confirm with yes | `--yes` (required for CI) |
| `codeclone setup apply --plan-id <ID>` | Bind apply to a previewed plan; fail if plan is stale | `--plan-id <ID>` |

### Safety guarantees

- **Confirmation-required**: interactive apply halts until you type `yes` or `no`
- **Plan binding**: `--plan-id` verifies plan hasn't changed; mismatch exits `2` (`status=stale_plan`)
- **Dry-run isolation**: `--dry-run` shows what would happen without touching files

## Common mistakes

**Mistake:** Running `setup apply --yes` on a stale plan from earlier in the session
**Fix:** Re-run `codeclone setup plan` and use the new `--plan-id`

**Mistake:** Running setup while another developer holds an active governance intent
**Fix:** Wait for their intent to clear, or coordinate scope separately

**Mistake:** Assuming readiness status is final before apply
**Fix:** Readiness is derived fresh during apply; edge-case config issues may appear then

## Next steps

After `setup apply` succeeds:

1. Review and commit the updated `pyproject.toml` and `.gitignore`
2. Generate your baseline: `codeclone . --update-baseline`, then commit `codeclone.baseline.json`
3. Run `codeclone .` to confirm the baseline is correct
4. Begin using controlled-change workflows for code modifications
