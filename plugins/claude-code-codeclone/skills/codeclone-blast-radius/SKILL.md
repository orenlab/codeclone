---
name: codeclone-blast-radius
description: Inspect structural blast radius before editing — dependents, clone cohort, risk signals, do-not-touch boundaries. Read-only; does not declare intent.
---

# CodeClone Blast Radius

Read-only impact inspection before editing specific files. Does NOT declare intent or
start a change workflow.

## Loop

```
analyze_repository(root=<abs>) → get_blast_radius(files=[...], depth="transitive")
```

`get_blast_radius` is current recomputation from the stored run. When
`start_controlled_change` returns a slim `blast_radius` summary with
`blast_artifact`, use `get_blast_artifact(root, run_id, blast_artifact_id)` for
the exact full evidence omitted from that start response. Do not substitute a
fresh `get_blast_radius` call when exact historical start evidence is required.
That slim start response is `context_governance.mode="partial_enforce"`; the
artifact retrieval response is `mode="observe"` because it returns the exact
stored object.

For a BUNDLED projection (blast + call_context + memory lanes + freshness + optional
`change_control` with `intent_id`), prefer `get_implementation_context`. Use this skill
when you need ONLY blast fields.

## Reading the response

> Key / easily-misread fields; the real response carries more.

| Field                                         | Meaning                                                                        |
|-----------------------------------------------|--------------------------------------------------------------------------------|
| `radius_level`                                | low / medium / high — overall risk bracket                                     |
| `origin`                                      | the files you asked about                                                      |
| `direct_dependents` / `transitive_dependents` | direct importers / reachable through chains                                    |
| `clone_cohort_members`                        | shares clone groups with origin — comparison context, NOT edit targets         |
| `in_dependency_cycle`                         | circular-import partners of origin                                             |
| `structural_risk`                             | high complexity / coupling, low coverage, overloaded modules in the blast zone |
| `do_not_touch`                                | HARD boundaries — separate explicit approval required                          |
| `review_context`                              | supporting context — NOT a ban on editing                                      |
| `guardrails`                                  | actionable review reminders                                                    |
| `blast_artifact`                              | exact retrieval pointer for full start-time blast evidence                     |

## Rules

- MCP tools only (CodeClone plugin). Absolute `root`. No latest run → `analyze_repository` first.
- Do not fall back to CLI / local report files. CodeClone is the source of truth.
- Present `do_not_touch` as hard boundaries, `clone_cohort_members` as comparison, `review_context` as informational.
- `radius_level` high → recommend `codeclone-change-control` for the actual edit.

## Output

Radius level + counts → risk signals (if any) → do-not-touch (if any) → guardrails →
recommendation (proceed / review dependents first / use change control). Concise.

## Non-goals

- Do not declare intent or start a change workflow (use `codeclone-change-control`).
- Do not auto-fix from blast results. Do not reinterpret CodeClone structural risk.
