---
name: codeclone-blast-radius
description: Inspect structural blast radius before editing files — shows dependents, clone cohort, risk signals, do-not-touch boundaries, and guardrails.
---

# CodeClone Blast Radius

Use this skill to understand the structural impact of changing specific files
before making edits. This is a read-only inspection — it does not declare
intent or start a change workflow.

## When to use

- Before a refactor: "What depends on this module?"
- Before renaming: "How many files will this affect?"
- Risk assessment: "Is this a high-risk change?"
- Planning: "What should I review before changing this?"

## Workflow

```
analyze_repository(root=<absolute_path>)
→ get_blast_radius(files=[...], depth="transitive")
```

## Reading the result

| Field | Meaning |
|---|---|
| `radius_level` | low / medium / high — overall risk bracket |
| `origin` | The files you asked about |
| `direct_dependents` | Files that directly import origin modules |
| `transitive_dependents` | Files reachable through dependency chains |
| `clone_cohort_members` | Files sharing clone groups with origin — comparison context, not edit targets |
| `in_dependency_cycle` | Files involved in circular imports with origin |
| `structural_risk` | Risk signals: high complexity, high coupling, low coverage, overloaded modules in the blast zone |
| `do_not_touch` | Hard boundaries — paths that require separate explicit approval |
| `review_context` | Supporting context for review — not a ban on editing |
| `guardrails` | Actionable review reminders |

## Rules

- Use MCP tools only when invoked through the CodeClone plugin.
- If no latest MCP run exists, call `analyze_repository` yourself first.
- Pass absolute `root` to analysis tools.
- Present `do_not_touch` as hard boundaries — do not suggest editing those paths.
- Present `clone_cohort_members` as comparison context, not as files to change.
- Present `review_context` as informational, not as a ban.
- If `radius_level` is high, recommend using `codeclone-change-control` for the
  actual edit workflow.

## Output format

Summarize concisely:

1. Radius level and file counts (origin, direct, transitive, clones).
2. Risk signals if any are non-empty.
3. Do-not-touch boundaries if present.
4. Guardrails.
5. Recommendation: proceed / review dependents first / use change control.

## Non-goals

- Do not declare intent or start a change workflow — use
  `codeclone-change-control` for that.
- Do not auto-fix or modify files based on blast radius results.
- Do not reinterpret CodeClone structural risk independently.
