### Report and finding projection tools

| Tool                  | Key parameters                                                                                                                                                        | Purpose                                                                                                                                                                         |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `get_report_section`  | `run_id`, `section`, `family`, `path`, `offset`, `limit`                                                                                                              | Read report sections; `metrics_detail` is paginated                                                                                                                             |
| `list_findings`       | `run_id`, `family`, `category`, `severity`, `source_kind`, `novelty`, `sort_by`, `detail_level`, changed-scope filters, `exclude_reviewed`, `max_results`, pagination | Filtered, paginated finding list. `exclude_reviewed=true` omits session-marked reviewed findings. `max_results` caps returned items (falls back to `limit`, hard-capped at 200) |
| `get_finding`         | `finding_id`, `run_id`, `detail_level`                                                                                                                                | One canonical finding by short or full ID                                                                                                                                       |
| `get_remediation`     | `finding_id`, `run_id`, `detail_level`                                                                                                                                | Remediation/explainability for one finding                                                                                                                                      |
| `list_hotspots`       | `kind`, `run_id`, `detail_level`, changed-scope filters, `limit`, `max_results`                                                                                       | Priority-ranked hotspot views by kind                                                                                                                                           |
| `generate_pr_summary` | `run_id`, `changed_paths`, `git_diff_ref`, `format`                                                                                                                   | PR-oriented markdown or JSON summary                                                                                                                                            |

`get_report_section` `section` accepts `meta`, `inventory`, `findings`,
`metrics`, `metrics_detail`, `changed`, `derived`, `integrity`, `module_map`,
or `all`. `section="module_map"` returns the exact
`report_document["derived"]["module_map"]` projection (graph views,
`unwind_candidates`, truncation, and `summary.available`) so agents read the
module map directly without `section="all"` or manual metrics-family joins. When
the run skipped the dependencies family the call returns the unavailable shell
(`summary.available: false`) rather than an error; only a run with no `derived`
section at all raises `MCPServiceContractError`.
