---
title: "Development guide"
audience: public
doc_type: guide
status: draft
source_commit: "582228177b2f57d9b9823ff1da9b6a0620f1297f"
---

# Development guide

## What it is

CodeClone's development workflow combines structural analysis of Python code with a change-control layer that guards repository edits. The core `codeclone` package provides CLI tools and structural metrics. An optional MCP surface adds AI-assisted workflow support through controlled edit cycles.

## When to use it

Use this guide if you are:
- Contributing code or documentation to CodeClone
- Setting up a development environment to work on the codebase
- Learning how CodeClone's structural contracts work in practice
- Preparing changes for review or release

## Basic workflow

```mermaid
graph LR
    A["Analyze<br/>(baseline run)"] --> B["Plan change<br/>(scope & intent)"]
    B --> C["Edit code<br/>(within scope)"]
    C --> D["Re-analyze<br/>(Python structural)"]
    D --> E["Validate & finish<br/>(scope check)"]
    E --> F["Commit & verify"]

    style A fill:#f9f,stroke:#333
    style B fill:#bbf,stroke:#333
    style C fill:#fbb,stroke:#333
    style D fill:#f9f,stroke:#333
    style E fill:#bfb,stroke:#333
    style F fill:#fbf,stroke:#333
```

The workflow ensures your changes respect structural boundaries and contract versions. For documentation-only changes, the cycle is lighter. For Python code changes, full structural verification is required.

## Key commands

| Task | Command | Notes |
|------|---------|-------|
| Install (base) | `uv sync` | Base package without MCP support |
| Install (with MCP) | `uv sync --all-extras` | Includes optional MCP surface |
| Analyze repository | `codeclone .` | Baseline structural run |
| Run tests | `uv run pytest -q` | Full test suite |
| Run pre-commit | `uv run pre-commit run --all-files` | Lint and format checks |
| View reports | Open `.codeclone/report.html` | Visual metrics and findings |

The MCP surface (when installed) provides additional workflow commands through your IDE or agent interface. It is optional; the base `codeclone` CLI works independently.

## Common mistakes

| Mistake | Impact | Prevention |
|---------|--------|-----------|
| Skipping analysis before editing | Undetected structural drift | Always run baseline analysis first |
| Editing files outside declared scope | Scope violation on finish | Declare full scope up front; expand only with approval |
| Using stale structural data | Missed regressions | Re-analyze after code changes before finishing |
| Mixing edit paths for Python files | Incomplete verification | Use workflow tools (not atomic) for Python structural changes |
| Hardcoding tool/contract counts | Version lockstep failures | Derive from source of truth (test fixtures, contract imports) |

The MCP surface fails closed: if not installed, edit-cycle tools are unavailable (the base CLI continues working). Do not assume MCP tools are present.

## Next steps

For detailed contribution requirements, validation commands, code style, and commit conventions, see the [normative contribution guide](https://github.com/orenlab/codeclone/blob/main/CONTRIBUTING.md) at the repository root. That guide covers:
- Full validation and test commands
- Commit message format and scopes
- Code style expectations
- Pre-commit hook requirements

Start with `uv sync`, review the current structural metrics with `codeclone .`, then work through your changes using the workflow above.
