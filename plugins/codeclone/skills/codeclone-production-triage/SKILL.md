---
name: codeclone-production-triage
description: Triage a Python repository against its CodeClone baseline — which findings are new since the baseline, production-first hotspots, and the recommended next review action. Requires a baseline; without one the regression view is empty. For worst-right-now, use codeclone-hotspots.
---

# CodeClone Production Triage

What changed against the baseline, production first: which findings the comparison
called new, the worst production hotspots, and the next review action.

## When to use

- "Production regressions vs baseline?" / "What to review first?" / "State of this repo?" / before starting a task.
- Needs a baseline: without one the comparison has nothing to report and `baseline.status`
  says so. For "worst hotspot?" or one metric on any repository, use `codeclone-hotspots`.
- Baseline-relative `new`/`known` is NOT patch-local proof; patch-local regressions need the change-control before→after
  verify.

## Loop

```
analyze_repository(root=<abs>) → get_production_triage
```

Two calls. Stop unless asked for more.

- Drill a hotspot: `get_finding(finding_id=…)` → `get_remediation(finding_id=…)`.
- Changed-files context:
  `analyze_changed_paths(root=…, changed_paths=[...]) → get_report_section(section="changed")`.
- Which findings trip the gate: `evaluate_gates(run_id=…, …)` →
  `list_findings(novelty="new", source_kind="production", family=…)`.

## Reading the response

> Key / easily-misread fields; the real response carries more.

| Field                                   | Meaning                                                        |
|-----------------------------------------|----------------------------------------------------------------|
| `health.score`/`grade`                  | 0–100 / A–F                                                    |
| `findings.total` / `production` / `new` | all / production-only / new since baseline                     |
| `new_by_source_kind`                    | new split prod / tests / fixtures (the gate counts production) |
| `baseline.status`                       | ok / mismatch / missing                                        |
| hotspot `severity` / `source_kind`      | impact class / production vs tests                             |
| `novelty`                               | baseline-relative, NOT patch-local                             |

## Rules

- MCP tools only (CodeClone plugin). Absolute `root`. No latest run → `analyze_repository` first.
- Default profile — triage, not a deep dive. Production hotspots first, tests/fixtures separately.
- Clean? Say so — do not invent concerns. Regressions? Suggest `codeclone-review`.
- Do not fall back to CLI / local report files. CodeClone is the source of truth.

## Output

Health + grade → counts (total / production / new) → top hotspots (≤5: path, kind,
severity) → baseline status → recommended next action. Concise — a snapshot.

## Non-goals

- Do not start a full review loop (use `codeclone-review`) or modify files / declare intent (use
  `codeclone-change-control`).
- Do not lower thresholds for "more findings" unless explicitly asked.
