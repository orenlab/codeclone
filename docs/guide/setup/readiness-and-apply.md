<!-- doc-scope: CANONICAL GUIDE for human setup readiness (Phase 37).
     owns: setup CLI workflow, plan/apply semantics, wizard UX, exit codes.
     does-not-own: full config key reference (→ book/10), MCP change control (→ guide/change-control). -->

# Repository setup and readiness

Use the **`codeclone setup`** command family to inspect whether a Python
repository is ready for CodeClone analysis, change control, Engineering Memory,
and optional audit — then apply **bounded, previewed** fixes to `pyproject.toml`
and `.gitignore`.

!!! important "CLI-only surface"
    Setup readiness is a **terminal CLI** workflow. It does not use MCP tools,
    does not declare change intent, and does not grant `edit_allowed`. Agent
    edit governance remains on the MCP change-control path documented in
    [Change control overview](../change-control/overview.md).

## When to use it

| Situation                             | Start with                    |
|---------------------------------------|-------------------------------|
| New repo or first CodeClone install   | `codeclone setup status`      |
| Verbose probe diagnostics             | `codeclone setup doctor`      |
| Scriptable diff preview before writes | `codeclone setup plan --json` |
| Apply the previewed merges            | `codeclone setup apply`       |
| Interactive hub and guided apply      | `codeclone setup wizard`      |

On a **mature** repository that already has `[tool.codeclone]`, audit enabled,
and `.gitignore` covering `.codeclone/`, `plan` returns **`status: empty`** —
that is expected, not a failure.

## Command reference

All subcommands accept **`--root PATH`** (default `.`).

| Subcommand         | Mutates files | `--json` | Notes                                              |
|--------------------|---------------|----------|----------------------------------------------------|
| `status` (default) | no            | yes      | Capability table and maturity rollup               |
| `doctor`           | no            | yes      | Same snapshot with verbose probe detail            |
| `plan`             | no            | yes      | Read-only diff previews per action                 |
| `apply`            | yes*          | yes      | Executes plan actions; `--dry-run` previews writes |
| `wizard`           | yes*          | no       | TTY + Rich required; hub menu and guided flow      |

\* `apply` and `wizard` only touch **`pyproject.toml`** (round-trip `[tool.codeclone]`
merge) and **`.gitignore`** (append `.codeclone/` when missing). They never
write baselines, analysis cache, or canonical reports.

### Typical flow

```bash
# 1. Readiness snapshot
codeclone setup status

# 2. Preview proposed merges (machine-readable for scripts)
codeclone setup plan --json

# 3. Apply (or dry-run first)
codeclone setup apply --dry-run
codeclone setup apply
```

### What `plan` / `apply` may change

When readiness probes show gaps, the engine derives deterministic actions:

1. **Missing `[tool.codeclone]`** — merge a section with default
   `baseline = "codeclone.baseline.json"`.
2. **Section present, `audit_enabled` false** — set `audit_enabled = true`
   (enables local Controller audit queries such as `codeclone --audit`).
3. **`.gitignore` missing `.codeclone/`** — append the suggested cache/state
   entry (idempotent; no duplicate lines).

Actions are blocked when `pyproject.toml` is missing or invalid — fix the
project file first, then re-run `plan`.

### Exit codes (`apply` only)

| `status` in JSON                      | Exit code | Meaning                                          |
|---------------------------------------|-----------|--------------------------------------------------|
| `applied`, `dry_run`, `empty`, `noop` | `0`       | Success                                          |
| `blocked`                             | `2`       | Preconditions failed (invalid/missing pyproject) |
| `failed`, `partial`                   | `5`       | Write or merge error                             |

`status`, `doctor`, and `plan` always exit `0` on successful projection
(errors print to stderr and exit `5`).

### Interactive wizard

```bash
codeclone setup wizard
```

Requires a **TTY** and **Rich** console support. The hub shows capability
spheres (`1`–`4`), **`g`** guided plan → confirm → apply, **`d`** doctor view,
and **`0`** quit. Use this when you prefer menus over flags; automation should
use `plan` / `apply --json` instead.

## Readiness capabilities (snapshot)

`status` and `doctor` project **capability axes** (install, configuration,
runtime) for spheres such as analysis, MCP, Engineering Memory, audit, and
optional extras (`semantic`, `analytics`, …). Maturity labels summarize how
far the repo is toward a fully governed workflow.

Full configuration keys live in [Config and Defaults](../../book/10-config-and-defaults.md).
Engineering Memory setup continues with `codeclone memory init` after analysis —
see [Engineering Memory overview](../memory/overview.md).

## Agent and IDE users

Plugins ship the **`codeclone-setup`** skill with the same CLI playbook. MCP
skills (`codeclone-change-control`, `codeclone-review`, …) assume analysis and
config readiness; run setup **before** connecting MCP when `[tool.codeclone]` or
gitignore hygiene is missing.

Integration guides link here for client-specific install order:

- [Codex](../integrations/codex/setup.md)
- [Cursor](../integrations/cursor/install-and-skills.md)
- [Claude Code](../integrations/claude-code/setup.md)

Normative CLI flag inventory: [CLI reference](../../book/11-cli.md).
