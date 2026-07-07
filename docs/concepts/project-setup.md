---
title: "Project setup"
audience: public
doc_type: concept
status: published
source_commit: "60eac9c367d74deeba1478521461addfedd8e681"
---

## What it is

Project setup is the process of preparing a repository for CodeClone governance. The `setup` command discovers project structure, evaluates readiness across **14 capabilities** (grouped into core analysis, governed agent workflows, project knowledge, and team & release), each scored on installation, configuration, and runtime axes, and plans a small set of filesystem changes: it merges the `[tool.codeclone]` section into `pyproject.toml` and appends CodeClone cache paths to `.gitignore`.

Setup is read-only until a plan is explicitly applied and confirmed — discovering and planning never write to disk on their own.

## Why it exists

Change control, Engineering Memory, and the audit trail all need governance config in `pyproject.toml` (and appropriate `.gitignore` entries) to be wired up correctly. Their databases — the workspace intent registry, the audit trail, the memory store — are created lazily at runtime the first time each feature runs; setup does **not** create them. Writing the config by hand is error-prone and easy to get subtly wrong (wrong gitignore entry, stale config key). Setup exists to make that bootstrap a single, safe, reviewable operation — plan first, then apply — rather than a set of manual file edits.

## How it fits together

Setup unlocks the rest of CodeClone's governance surface; nothing else requires it for read-only analysis:

| Capability | Requires setup? |
|------------|-------------------|
| Plain `codeclone .` analysis | No |
| [Controlled change](controlled-change.md) intent tracking | Yes — needs the governance config setup writes (the intent/audit databases are created on first use) |
| [Engineering Memory](engineering-memory.md) | Yes — needs its config wired up (the store is initialized on first use) |
| CI gating on a baseline | No — a baseline can be created without running setup |

```mermaid
graph LR
    A["setup plan"] --> B["capability readiness (14 capabilities)"]
    B -->|pass| C["setup apply"]
    B -->|fail| D["fix environment/config"]
    D --> A
    C --> E["pyproject.toml + .gitignore updated"]
    E --> F["Controlled change + Engineering Memory available"]
```

Applying a plan is a two-step contract by design: `--dry-run` previews the mutation with no writes, and `--plan-id` binds the actual apply to that exact previewed plan — if the repository changed in between, apply refuses with `status=stale_plan` rather than writing something that was never reviewed.

## Related pages

- [Set up a project](../guides/setup-project.md) — the concrete commands
- [Setup command reference](../reference/setup.md)
- [Controlled change](controlled-change.md) — what setup unlocks
