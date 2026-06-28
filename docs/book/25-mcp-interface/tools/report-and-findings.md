### Report and finding projection tools

| Tool                  | Key parameters                                                                                                                                                        | Purpose                                                                                                                                                                                                                                                                      |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `get_report_section`  | `run_id`, `section`, `family`, `path`, `offset`, `limit`                                                                                                              | Read report sections; `metrics_detail` is paginated                                                                                                                                                                                                                          |
| `list_findings`       | `run_id`, `family`, `category`, `severity`, `source_kind`, `novelty`, `sort_by`, `detail_level`, changed-scope filters, `exclude_reviewed`, `max_results`, pagination | Filtered, paginated finding list. Each item includes `short_id`, `canonical_id`, and `html_anchor` alongside the finding body. `exclude_reviewed=true` omits session-marked reviewed findings. `max_results` caps returned items (falls back to `limit`, hard-capped at 200) |
| `get_finding`         | `finding_id`, `run_id`, `detail_level`                                                                                                                                | One finding by short or canonical ID. Unknown ids return `status="not_found"` with `accepted_id_forms` and `next_tool` instead of raising (MCP resource `findings/{id}` still raises when the id is absent)                                                                  |
| `get_remediation`     | `finding_id`, `run_id`, `detail_level`                                                                                                                                | Remediation/explainability for one finding. Unknown ids raise a contract error; use `get_finding` first when accepting user-provided IDs                                                                                                                                     |
| `list_hotspots`       | `kind`, `run_id`, `detail_level`, changed-scope filters, `exclude_reviewed`, `limit`, `max_results`                                                                   | Priority-ranked hotspot views by kind. `kind` is `most_actionable`, `highest_spread`, `highest_priority`, `production_hotspots`, or `test_fixture_hotspots`; `max_results` is hard-capped at 50. When `items` is empty, `empty_reason` explains why                          |
| `generate_pr_summary` | `run_id`, `changed_paths`, `git_diff_ref`, `format`                                                                                                                   | PR-oriented markdown or JSON summary                                                                                                                                                                                                                                         |

`get_report_section` `section` accepts `meta`, `inventory`, `findings`,
`metrics`, `metrics_detail`, `changed`, `derived`, `integrity`, `module_map`,
or `all`. `section="module_map"` returns the exact
`report_document["derived"]["module_map"]` projection (graph views,
`unwind_candidates`, truncation, and `summary.available`) so agents read the
module map directly without `section="all"` or manual metrics-family joins. When
the run skipped the dependencies family the call returns the unavailable shell
(`summary.available: false`) rather than an error; only a run with no `derived`
section at all raises `MCPServiceContractError`.

`list_hotspots.empty_reason` is a closed explanatory string, not a failure:
`no_findings_in_run`, `changed_paths_filter_excluded_all`,
`all_items_reviewed`, `no_ranked_findings`, `unsupported_hotlist_kind`,
`no_items_above_actionability_threshold`, `no_spread_hotspots`,
`no_production_hotspots`, `no_test_fixture_hotspots`, `hotlist_unpopulated`, or
`hotlist_items_filtered_or_unavailable`.
