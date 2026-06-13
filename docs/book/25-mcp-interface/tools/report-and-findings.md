### Report and finding projection tools

| Tool                  | Key parameters                                                                                                                     | Purpose                                             |
|-----------------------|------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------|
| `get_report_section`  | `run_id`, `section`, `family`, `path`, `offset`, `limit`                                                                           | Read report sections; `metrics_detail` is paginated |
| `list_findings`       | `run_id`, `family`, `category`, `severity`, `source_kind`, `novelty`, `sort_by`, `detail_level`, changed-scope filters, pagination | Filtered, paginated finding list                    |
| `get_finding`         | `finding_id`, `run_id`, `detail_level`                                                                                             | One canonical finding by short or full ID           |
| `get_remediation`     | `finding_id`, `run_id`, `detail_level`                                                                                             | Remediation/explainability for one finding          |
| `list_hotspots`       | `kind`, `run_id`, `detail_level`, changed-scope filters, `limit`, `max_results`                                                    | Priority-ranked hotspot views by kind               |
| `generate_pr_summary` | `run_id`, `changed_paths`, `git_diff_ref`, `format`                                                                                | PR-oriented markdown or JSON summary                |
