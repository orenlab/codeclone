---
name: codeclone-hotspots
description: Rank what is worst in a Python repository right now — health, top hotspots, or one metric. Needs no baseline and answers on a repository that has never had one. For what changed against a baseline, use codeclone-production-triage.
---

# CodeClone Hotspots

What is worst **right now** — ranked inside the current run, never against a previous one.

## When to use

- "Worst hotspots?" / "Complexity hotspots?" / "How healthy is this repo?" / pre-merge sanity.
- No baseline in the repository, or you do not care what changed: this is the skill that still answers.
- "What changed since the baseline?" is the other question — use `codeclone-production-triage`.
- "Did my patch cause this?" is neither — use the change-control before→after verify path.

## Loop

```
analyze_repository(root=<abs>) → list_hotspots(kind="production_hotspots")
```

Cheapest useful path. Stop there unless asked for more. `health.score` / `grade` / `dimensions` ride
the `analyze_repository` response itself — no second call for the health question.

- Other rankings: `list_hotspots(kind="most_actionable")`, `list_hotspots(kind="highest_priority")`,
  `list_hotspots(kind="highest_spread")`, `list_hotspots(kind="test_fixture_hotspots")`.
- Specific metric:
  `analyze_repository → check_complexity | check_coupling | check_cohesion | check_dead_code | check_clones`
- Adoption / API surface / coverage join: `get_report_section(section="metrics")` (coverage unclear →
  `help(topic="coverage")`)
- Drill one row: `get_finding(finding_id=…)` → `get_remediation(finding_id=…)`.

## Reading the response

> Key / easily-misread fields; the real response carries more.

| Field                        | Meaning                                                                   |
|------------------------------|---------------------------------------------------------------------------|
| `kind`                       | which ranking was requested — an ordering, not a severity filter          |
| `total` vs `returned`        | how many rank under that kind; how many this call carried back            |
| item `severity` / `priority` | impact class; composite rank within this run                              |
| item `scope`                 | production vs tests vs fixtures                                           |
| item `spread`                | how widely the finding is distributed                                     |
| item `novelty`               | baseline-relative — `unavailable` when nothing compared it; see below     |
| `empty_reason`               | why a ranking came back empty (no findings of that kind, all reviewed, …) |

`list_hotspots` runs no baseline comparison. Its response carries no `baseline` block and no
new-vs-known count, so it cannot say what a patch or a release regressed. The per-item `novelty` is
carried through from the run and reads `unavailable` when nothing compared it — it is not a
regression report. For that, and for `baseline.status`, use `codeclone-production-triage`.

## Rules

- MCP tools only (CodeClone plugin). Absolute `root`. No latest run → `analyze_repository` first.
- Default thresholds — this is a quick check. `detail_level` for lists: summary | normal | full.
- One precise call beats three. Summarize concisely — a snapshot, not a report.
- Do not fall back to CLI / local report files. CodeClone is the source of truth.
- If results look concerning, suggest `codeclone-review` for a real session.
