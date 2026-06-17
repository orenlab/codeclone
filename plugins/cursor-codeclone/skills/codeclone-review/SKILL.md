---
name: codeclone-review
description: Review a Python repository via CodeClone MCP — first pass, baseline triage, changed-files review, and the findings that trip the gates.
---

# CodeClone Review

Structural / clone / changed-scope / gate review. Read-only; never mutates state.

## Rules

- MCP tools only (CodeClone plugin). Absolute `root`. CodeClone is the source of truth — never reinterpret, suppress, or
  mutate.
- No latest run → `analyze_repository` / `analyze_changed_paths` first.
- Default / pyproject thresholds on the first pass. Lower thresholds = explicit exploratory follow-up, never silent.
- Production- and changed-files-first over broad listing. `detail_level` for lists: summary | normal | full.

## Workflows

- Full: `analyze_repository → get_production_triage → list_hotspots → get_finding → get_remediation`
- PR:
  `analyze_changed_paths → get_report_section(section="changed") → list_findings(changed_paths=…, sort_by="priority") → generate_pr_summary`
- Metrics / coverage: `get_report_section(section="metrics")` (coverage join → `help(topic="coverage")`)
- Deeper: `help(topic="analysis_profile")` → re-analyze with lower thresholds → `compare_runs`

## Gates → the findings that trip them

- `evaluate_gates(run_id, fail_on_new=, fail_complexity=, fail_coupling=, fail_dead_code=, fail_health=, …)` → gate
  decision.
- See the findings behind a `reasons[]` token:
  `list_findings(novelty="new", family="clones"|"complexity"|…, source_kind="production")`.
- Per-family, new vs known: `check_clones | check_complexity | check_coupling | check_cohesion | check_dead_code`.
- Drill one: `get_finding(finding_id)` → `get_remediation(finding_id)`.
- Review loop: `mark_finding_reviewed(finding_id) → list_reviewed_findings`; `exclude_reviewed=true` in long sessions.

## Reading the response

> Key / easily-misread fields; the real response carries more.

| Field                                     | Meaning                                                                       |
|-------------------------------------------|-------------------------------------------------------------------------------|
| `health.score`/`grade`                    | 0–100 / A–F; `dimensions` = per-family scores                                 |
| `findings.new`/`known`                    | baseline-relative novelty — NOT patch-local proof (use change-control verify) |
| `new_by_source_kind`                      | new split prod / tests / fixtures (the gate counts production)                |
| `evaluate_gates.would_fail` + `reasons[]` | gate verdict + cause tokens (`clone:new`, `health`, …)                        |
| finding `severity` vs `priority`          | severity = impact class; priority = ranked action order                       |
| finding `source_kind`                     | production / tests / fixtures — filter test noise                             |
| `novelty="known"`                         | in baseline, NOT "safe" — a patch may reintroduce it                          |

## Non-goals

- No auto-suppress, no mutate. `overloaded_modules` = report-only context, not a finding/gate.
- A clean default pass ≠ proof no finer-grained issues exist. Do not fall back to CLI / local report files.
