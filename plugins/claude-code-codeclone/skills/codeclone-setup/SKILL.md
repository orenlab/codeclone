---
name: codeclone-setup
description: Human repository setup readiness — status, plan, apply, and wizard over the CLI (not MCP).
---

# CodeClone Setup (CLI)

Inspect and configure repository readiness **before** MCP change control or
full review workflows. This skill is **CLI-only** — no MCP tools, no
`start_controlled_change`, no `edit_allowed`.

## When to use

- New repo, missing `[tool.codeclone]`, audit disabled, or `.gitignore` lacks `.codeclone/`.
- Human or agent needs a **previewed** pyproject/gitignore fix without touching baselines or reports.
- Prefer menus: `codeclone setup wizard` (TTY + Rich).

Do **not** use for governed code edits — use `codeclone-change-control`.

## Loop

```
codeclone setup status          # capability snapshot (default)
codeclone setup doctor          # verbose probes
codeclone setup plan [--json]   # read-only diff preview
codeclone setup apply [--dry-run] [--json]
codeclone setup wizard          # interactive hub (no --json)
```

All commands accept `--root <abs-or-rel-path>`.

## What apply changes (bounded)

- Round-trip merge into **`pyproject.toml`** `[tool.codeclone]` only:
    - add section + default `baseline` when missing;
    - set `audit_enabled = true` when section exists but audit is off.
- Append **`.codeclone/`** to `.gitignore` when not already covered.

Never writes `codeclone.baseline.json`, `.codeclone/cache`, or report artifacts.

## Exit codes (apply)

| JSON `status`                  | Exit |
|--------------------------------|------|
| `applied`, `preview`, `noop`   | 0    |
| `blocked`                      | 2    |
| `failed`, `partial`            | 5    |

(`preview` when `--dry-run`; `plan` uses `status=empty`.)

## Rules

- Run in the user's terminal (or subprocess), not via MCP.
- Mature repos may show **`plan` → empty** — expected.
- After setup, continue with `codeclone .` and MCP skills as needed.
- Full guide: docs site *Repository setup and readiness* (`docs/guide/setup/readiness-and-apply.md`).
