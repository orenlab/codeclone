---
name: codeclone-production-triage
description: Quick production triage with baseline-relative regressions and next review action.
---

# CodeClone Production Triage

Use this skill for a fast, production-focused first pass over the repository.
Returns health score, top hotspots, baseline-relative regressions, and the
recommended next action without entering a full review loop.

## When to use

- "What's the state of this repo?"
- "Any production regressions relative to the baseline?"
- "What should I review first?"
- Before starting work on a new task.
- Quick standup-level quality snapshot.

This is baseline-relative triage. Do not use `new`/`known` novelty alone as
patch-local proof; patch-local regressions require before-run to after-run
verify evidence.

## Workflow

```
analyze_repository(root=<absolute_path>)
→ get_production_triage
```

That's two MCP calls. Stop there unless the user asks for more.

### If the user wants to drill into a specific hotspot

```
get_finding(finding_id=...)
→ get_remediation(finding_id=...)
```

### If the user wants to see changed-files context

```
analyze_changed_paths(root=..., paths=[...])
→ get_report_section(section="changed")
```

## Rules

- Use MCP tools only when invoked through the CodeClone plugin.
- If no latest MCP run exists, call `analyze_repository` yourself first.
- Use the default analysis profile — this is a triage pass, not a deep dive.
- Pass absolute `root` to analysis tools.
- Present production hotspots first, then test/fixture findings separately.
- Do not lower thresholds on the first pass.
- If results look clean, say so. Do not invent concerns.
- If results show regressions, suggest `codeclone-review` for a proper session.
- Do not reinterpret findings — CodeClone is the source of truth.

## Output format

Summarize in this order:

1. Health score and grade.
2. Finding counts: total, production, new since baseline.
3. Top hotspots (up to 5) with file path, kind, and severity.
4. Baseline status (ok / mismatch / missing).
5. Recommended next action.

Keep it concise — the user wants a snapshot, not a report.

## Non-goals

- Do not start a full review loop — use `codeclone-review` for that.
- Do not modify files or declare intent — use `codeclone-change-control`.
- Do not lower thresholds for "more findings" unless the user explicitly asks.
