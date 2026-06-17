---
name: codeclone-platform-observability
description: Maintainer-only — diagnose CodeClone's own runtime via Platform Observability after explicit observer enable. Not for end users analyzing their Python repository.
---

# CodeClone Platform Observability (maintainer-only)

Use this skill **only when developing CodeClone itself** — instrumentation,
MCP server, memory pipelines, projection workers, or observer storage/rendering.

## Who this is for

| Audience                                    | Use this skill?                                                          |
|---------------------------------------------|--------------------------------------------------------------------------|
| CodeClone maintainers / contributors        | **Yes** — after explicit observer setup                                  |
| Users analyzing **their** Python repository | **No** — use `codeclone-review`, `codeclone-hotspots`, or change control |
| Repository quality / CI / gate questions    | **No** — observer data is not analysis truth                             |

`query_platform_observability` and `codeclone observability trace` explain
**CodeClone's execution**, not the analyzed project's code quality. High DB
activity means CodeClone ran SQL — not that the user's repo has a database
problem.

## Prerequisites (mandatory)

Observation is **disabled by default**. Without explicit enablement the MCP
tool returns `status=disabled` or `status=no_store` — it does not error and
does not change analysis behavior.

Before any diagnostic call:

```bash
export CODECLONE_OBSERVABILITY_ENABLED=1
```

Restart the **same process** that will produce telemetry (CLI, `codeclone-mcp`,
or projection worker) with that variable set. A store appears only after at
least one instrumented operation completes:

`.codeclone/db/platform_observability.sqlite3`

Optional (see contract):

```bash
export CODECLONE_OBSERVABILITY_PROFILE=1   # requires codeclone[perf]
export CODECLONE_OBSERVABILITY_PERSIST=0   # instrument without persisting
```

There is **no** `[tool.codeclone.observability]` pyproject table — env only.

## When to use

- "Why is this MCP call slow?"
- "Which tools dominate payload size?"
- "Memory semantic rebuild cost?"
- "Correlate CLI → MCP → worker spans"
- Debugging changes under `codeclone/observability/` or MCP instrumentation

## When NOT to use

- End-user repo review, triage, clones, dead code, health score
- Patch verify, blast radius, or edit authorization
- Inferring repository defects from observer metrics

## Workflow

```
help(topic="observability")   # contract + anti-patterns (optional first)
→ reproduce with CODECLONE_OBSERVABILITY_ENABLED=1
→ query_platform_observability(section=summary, window=latest)
→ follow recommended_next_sections (one section per call)
```

### MCP drill-down (one section per call)

Start at `summary`, then as needed:

| Section                | Use when                           |
|------------------------|------------------------------------|
| `slow_operations`      | Latency outliers                   |
| `mcp_tool_matrix`      | Tool frequency / payload pressure  |
| `db_cost`              | SQL fingerprint cost               |
| `memory_pipeline_cost` | Semantic rebuild / embedding spans |
| `correlated_chains`    | Cross-process workflow             |
| `costly_noops`         | Redundant work hints               |
| `pipeline`             | Analysis pipeline breakdown        |
| `agent_context`        | Session / surface context          |

Parameters: absolute `root`, `detail_level=compact|normal`, `limit` 1–50,
`window=latest` or correlation id.

### Human cockpit (not MCP)

For the full waterfall HTML view (maintainers):

```bash
codeclone observability trace --root . --last 50 --html /tmp/codeclone-observer.html
```

Agents use bounded MCP sections; humans use CLI HTML/JSON.

## Rules

- Use MCP tools only when invoked through the CodeClone plugin.
- Do not fall back to CLI or local report files for repository analysis.
- Never treat observer metrics as findings, gates, or edit permission.
- Never use telemetry to claim user-repo quality regressions.
- If `status=disabled` or `no_store`, stop and verify env + reproducer process —
  do not retry blindly.
- After changing instrumentation, run `tests/test_observability_*.py`.

Contract: `docs/book/26-platform-observability.md`, guide:
`docs/guide/observability/maintainer-workflow.md`.
