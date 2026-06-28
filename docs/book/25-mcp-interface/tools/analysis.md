### Analysis and run-level tools

| Tool                         | Key parameters                                                                                                                                                                                                                                                                                                                              | Purpose                                                                                                                                                                                                              |
|------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `analyze_repository`         | `root`, `analysis_mode`, thresholds, `api_surface`, `coverage_xml`, `baseline_path`, `metrics_baseline_path`, `cache_policy`, `allow_external_artifacts`, `changed_paths` or `git_diff_ref`                                                                                                                                                 | Full deterministic analysis; registers an in-memory run                                                                                                                                                              |
| `analyze_changed_paths`      | `root`, `changed_paths` or `git_diff_ref`, `analysis_mode`, thresholds, `api_surface`, `coverage_xml`, `cache_policy`, `allow_external_artifacts`                                                                                                                                                                                           | Diff-aware analysis with changed-files projection                                                                                                                                                                    |
| `get_run_summary`            | `run_id`                                                                                                                                                                                                                                                                                                                                    | Cheapest run-level snapshot: health, findings, baseline/cache status                                                                                                                                                 |
| `get_production_triage`      | `run_id`, `max_hotspots`, `max_suggestions`                                                                                                                                                                                                                                                                                                 | Production-first first-pass view                                                                                                                                                                                     |
| `get_implementation_context` | `root`, `paths`, `symbols`, `intent_id`, `changed_scope`, `mode`, `include`, `depth`, `detail_level`, `budget`, `run_id`                                                                                                                                                                                                                    | Bounded, drift-aware structural context from one stored run                                                                                                                                                          |
| `compare_runs`               | `run_id_before`, optional `run_id_after`, `focus`                                                                                                                                                                                                                                                                                           | Run-to-run delta; `run_id_after` defaults to the latest run; returns `incomparable` when roots/settings differ                                                                                                       |
| `evaluate_gates`             | `run_id`, gate flags (`fail_on_new`, `fail_threshold`, `fail_complexity`, `fail_coupling`, `fail_cohesion`, `fail_cycles`, `fail_dead_code`, `fail_health`, `fail_on_new_metrics`, `fail_on_typing_regression`, `fail_on_docstring_regression`, `fail_on_api_break`, `fail_on_untested_hotspots`, `min_typing_coverage`, …), `coverage_min` | Preview CI gating decisions without mutating state — same gate vocabulary as [CLI flags](../../11-cli.md) and [Metrics and quality gates](../../16-metrics-and-quality-gates.md); threshold ints use `-1` to disable |
| `help`                       | `topic`, `detail`                                                                                                                                                                                                                                                                                                                           | Bounded workflow/contract guidance — see [Help topics](help-and-topics.md)                                                                                                                                           |

`allow_external_artifacts` (default `false`): when `true`, optional artifact
path parameters may resolve to absolute or out-of-repo locations. See
[Security Model](../../21-security-model.md).

Selected analysis and workflow responses may include non-blocking `tips[]`
entries for workspace hygiene (for example when `.codeclone/` is not
covered by the repository root `.gitignore`). The CLI prints the same
advisory after interactive analysis runs (suppressed in `--quiet`, CI, and
non-TTY contexts). Tips are advisory only; MCP and CLI never edit
`.gitignore` automatically.

## Implementation context

`get_implementation_context` projects bounded structural, call-graph, contract,
and memory evidence from one stored run. It is read-only and never authorizes
edits.

Compact and normal responses include `context_governance` with
`mode="partial_enforce"` and
`evidence_policy="response_budget_with_exact_facet_pages"`. Mandatory subject
and freshness facts remain inline; large facet lanes may be omitted with exact
`get_implementation_context_page` drill-down metadata under
`context_governance.omitted`. The existing `budget_summary` remains an
item-count budget for context entries; `context_governance.limit` is the
serialized response budget. `detail_level="full"` and facet page retrieval stay
in `mode="observe"`.

Key parameters:

- `changed_scope` — when `true`, use the bounded live git-dirty set as the
  subject; mutually exclusive with explicit `paths` or `symbols`.
- `mode` — `implementation` (default), `impact`, or `contract`.
- `budget` — global evidence cap; safety entries can trigger
  `status="safety_context_overflow"`.
- `freshness.status="drifted"` — re-analyze before relying on the projection.

Full contract (modes, facets, digests, intent pinning, symbol resolution):
[Implementation context](implementation-context.md). Quick orientation:
`help(topic=implementation_context)`.
