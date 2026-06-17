---
name: codeclone-hotspots
description: Fast CodeClone quality snapshot — health, top risks, or one metric, without a full review loop.
---

# CodeClone Hotspots

Fast quality answer (health, worst hotspots, one metric) — not a full review session.

## When to use

- "How healthy is this repo?" / "Worst hotspots?" / "Complexity hotspots?" / pre-merge sanity.
- Baseline-relative `new`/`known` is NOT patch-local proof — for "did my patch cause this?" use the change-control
  before→after verify path.

## Loop

```
analyze_repository(root=<abs>) → get_production_triage
```

Cheapest useful path. Stop there unless asked for more.

- Specific metric:
  `analyze_repository → check_complexity | check_coupling | check_cohesion | check_dead_code | check_clones`
- Adoption / API surface / coverage join: `get_report_section(section="metrics")` (coverage unclear →
  `help(topic="coverage")`)
- Gate preview → its findings: `evaluate_gates(run_id, fail_on_new=, fail_complexity=, …)` → for the actual findings,
  `list_findings(novelty="new", family=…, source_kind="production")`.

## Reading the response

> Key / easily-misread fields; the real response carries more.

| Field                                         | Meaning                                                        |
|-----------------------------------------------|----------------------------------------------------------------|
| `health.score`/`grade`                        | 0–100 / A–F; `dimensions` = per-family                         |
| `findings.new`/`known`                        | baseline-relative — NOT patch-local proof                      |
| `new_by_source_kind`                          | new split prod / tests / fixtures (the gate counts production) |
| `evaluate_gates.would_fail` + `reasons[]`     | gate verdict + cause tokens                                    |
| check item `novelty` / `clone_type` / `scope` | new vs known / Type-1..4 / production vs tests                 |

## Rules

- MCP tools only (CodeClone plugin). Absolute `root`. No latest run → `analyze_repository` first.
- Default thresholds — this is a quick check. `detail_level` for lists: summary | normal | full.
- One precise call beats three. Summarize concisely — a snapshot, not a report.
- Do not fall back to CLI / local report files. CodeClone is the source of truth.
- If results look concerning, suggest `codeclone-review` for a real session.
