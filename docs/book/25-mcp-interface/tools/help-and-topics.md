# Help topics

The `help` tool returns bounded workflow and contract guidance without pulling
canonical report payloads. Call `help(topic=…)` after analysis when tool or
profile semantics are unclear.

---

## Parameters

| Parameter | Default      | Values                                                                                          |
|-----------|--------------|-------------------------------------------------------------------------------------------------|
| `topic`   | — (required) | One of the 15 topics below                                                                      |
| `detail`  | `compact`    | `compact` (summary, key points, recommended tools, anti-patterns) or `normal` (adds `warnings`) |

`compact` always includes `anti_patterns` when the topic defines them. `normal`
adds `warnings`. Both levels return `summary`, `key_points`, `recommended_tools`,
and `doc_links`.

---

## Topic catalog

| Topic                    | Summary focus                                               | Recommended first tools                                        |
|--------------------------|-------------------------------------------------------------|----------------------------------------------------------------|
| `overview`               | Topic index and budget-aware drill-down pointers            | `help`, `analyze_repository`, `get_production_triage`          |
| `workflow`               | Triage-first, budget-aware MCP usage                        | `analyze_repository`, `get_production_triage`, `list_hotspots` |
| `analysis_profile`       | Conservative default thresholds vs exploratory lower limits | `analyze_repository`, `compare_runs`                           |
| `suppressions`           | Declaration-scoped inline ignore policy                     | `get_finding`, `get_remediation`                               |
| `baseline`               | Trusted comparison snapshot and baseline-relative novelty   | `get_run_summary`, `evaluate_gates`, `compare_runs`            |
| `coverage`               | Cobertura join as current-run signal only                   | `analyze_repository`, `get_report_section`                     |
| `latest_runs`            | Session-local `latest/*` resource handles                   | `analyze_repository`, `get_run_summary`                        |
| `review_state`           | Session-local reviewed markers                              | `mark_finding_reviewed`, `list_hotspots`                       |
| `changed_scope`          | PR/patch-focused changed-files review                       | `analyze_changed_paths`, `generate_pr_summary`                 |
| `change_control`         | `start` / `finish` edit cycle                               | `start_controlled_change`, `finish_controlled_change`          |
| `trust_boundaries`       | Read-only MCP, artifact paths, Security Surfaces inventory  | `help`, `get_run_summary`                                      |
| `implementation_context` | Bounded context from one stored run                         | `get_implementation_context`                                   |
| `observability`          | Dev-only Platform Observability slicer                      | `query_platform_observability`                                 |
| `engineering_memory`     | Scoped memory retrieval and draft writes                    | `get_relevant_memory`, `query_engineering_memory`              |
| `verification_profiles`  | Finish-derived verification profiles and after-run rules    | `finish_controlled_change`, `analyze_repository`               |

---

## When to call

| Situation                                | Topic                       |
|------------------------------------------|-----------------------------|
| First MCP session on a repository        | `overview`, then `workflow` |
| Threshold or sensitivity questions       | `analysis_profile`          |
| Baseline / new-vs-known confusion        | `baseline`                  |
| Before declaring an edit intent          | `change_control`            |
| Finish blocked on after-run / profile    | `verification_profiles`     |
| `get_implementation_context` facets      | `implementation_context`    |
| Memory lanes, drafts, trajectories       | `engineering_memory`        |
| HTTP auth, artifact paths, read-only     | `trust_boundaries`          |
| Debugging CodeClone runtime (maintainer) | `observability`             |

---

## Maintainer-only: `observability`

Call `help(topic="observability")` and use `query_platform_observability` **only**
when developing **CodeClone itself** — not when reviewing a user's Python
repository. Requires `CODECLONE_OBSERVABILITY_ENABLED=1` on the producing
process before any store exists. See
[Maintainer workflow](../../../guide/observability/maintainer-workflow.md).

---

## Related

- Tool parameters: [Analysis tools](analysis.md)
- Implementation context contract: [Implementation context](implementation-context.md)
- Engineering Memory playbook: [Engineering Memory](../../13-engineering-memory/index.md)
