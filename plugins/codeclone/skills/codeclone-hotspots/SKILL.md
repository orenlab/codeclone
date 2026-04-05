---
name: codeclone-hotspots
description: Use for quick CodeClone hotspot discovery — health check, top risks, or a single-question quality snapshot without a full review loop.
---

# CodeClone Hotspots

Use this skill when the user wants a fast quality snapshot — not a full review
session but a quick answer about health, top risks, or a specific metric.

## When to use

- "How healthy is this repo?"
- "What are the worst hotspots?"
- "Any new regressions since the baseline?"
- "Show me the complexity hotspots."
- Quick pre-merge sanity checks.

## Workflow

```
analyze_repository → get_production_triage
```

That's the cheapest useful path. Stop there unless the user asks for more.

### If the user asks about a specific metric

```
analyze_repository → check_complexity | check_coupling | check_cohesion | check_dead_code | check_clones
```

### If the user wants a gate preview

```
analyze_repository → evaluate_gates
```

## Rules

- Use MCP tools only when invoked through the CodeClone plugin.
- If no latest MCP run exists, call `analyze_repository` yourself before reading `latest/*` resources.
- Use default thresholds — this is a quick check, not an exploratory deep-dive.
- One tool call is better than three when answering a simple question.
- Summarize concisely — the user wants a snapshot, not a report.
- Do not fall back to CLI or local report files.
- If the result looks concerning, suggest using `codeclone-review` for a proper session.
