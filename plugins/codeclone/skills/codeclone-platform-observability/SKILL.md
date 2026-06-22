---
name: codeclone-platform-observability
description: Maintainer-only — diagnose CodeClone's OWN runtime via Platform Observability after explicit observer enable. Not a user-repo quality signal.
---

# CodeClone Platform Observability (maintainer-only)

Use ONLY when developing CodeClone itself (instrumentation, MCP server, memory
pipelines, projection workers, observer storage/rendering). It explains CodeClone's
execution — NOT the analyzed project's code quality. High DB activity = CodeClone ran
SQL, not a user-repo defect.

| Audience                             | Use?                                                                |
|--------------------------------------|---------------------------------------------------------------------|
| CodeClone maintainers / contributors | yes — after explicit observer setup                                 |
| Users analyzing THEIR repo           | no — use `codeclone-review` / `codeclone-hotspots` / change control |
| Repo quality / CI / gate questions   | no — observer data is not analysis truth                            |

## Prerequisites (mandatory)

Disabled by default → the tool returns `status=disabled` / `no_store` (no error, no
behavior change). Before any diagnostic:

```bash
export CODECLONE_OBSERVABILITY_ENABLED=1
```

Restart the SAME process that produces telemetry (CLI, `codeclone-mcp`, or projection
worker). A store appears only after one instrumented op completes:
`.codeclone/db/platform_observability.sqlite3`. There is no
`[tool.codeclone.observability]` pyproject table — env only.

## Loop

```
help(topic="observability")   # contract + anti-patterns (optional)
→ reproduce with CODECLONE_OBSERVABILITY_ENABLED=1
→ query_platform_observability(section="summary", window="latest")
→ follow recommended_next_sections, ONE section per call
```

Sections:
`summary | slow_operations | mcp_tool_matrix | db_cost | memory_pipeline_cost | correlated_chains | costly_noops | pipeline | agent_context`.
Params: absolute `root`, `detail_level=compact|normal`, `limit` 1–50, `window=latest`
or a correlation id.

Human cockpit (not MCP): `codeclone observability trace --root . --last 50 --html /tmp/x.html`.

## Reading the response

> Key / easily-misread fields; the real response carries more.

| Field                                                | Meaning                                                                                 |
|------------------------------------------------------|-----------------------------------------------------------------------------------------|
| `status`                                             | ok / disabled / no_store (stop → verify env + reproducer process; do not retry blindly) |
| `recommended_next_sections`                          | follow these, one per call                                                              |
| row `verdict`                                        | `query_chatty` / `context_heavy` / `ok` — perf signal, NOT a code-quality verdict       |
| `costly_noops`                                       | redundant-work hints                                                                    |
| `affects_analysis_truth` / `affects_edit_permission` | always false — observer never gates or authorizes                                       |

MCP payload context metrics are estimated context units. For responses carrying
`context_governance`, the observer uses that envelope's `estimated` value; do not
describe it as an exact model tokenizer count.

## Non-goals

- Never treat observer metrics as findings, gates, or edit permission.
- Never infer user-repo regressions from telemetry.
- After changing instrumentation, run `tests/test_observability_*.py`.
