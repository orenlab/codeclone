<!-- doc-scope: MCP drill down. class: guide max-lines: 120 -->

# Drill down & focused checks

### Step 3: Drill Down

| Tool                  | Purpose                                                                                                              |
|-----------------------|----------------------------------------------------------------------------------------------------------------------|
| `list_findings`       | Filtered, paginated findings with novelty and scope filters; items include `short_id`, `canonical_id`, `html_anchor` |
| `get_finding`         | Single finding by short or canonical ID; unknown ids return `status="not_found"` instead of raising                  |
| `get_remediation`     | Remediation and explainability for one finding                                                                       |
| `list_hotspots`       | Ranked hotspot views; empty `items` include `empty_reason`                                                           |
| `get_report_section`  | Read report sections; `metrics_detail` is paginated                                                                  |
| `evaluate_gates`      | Preview CI gating decisions without mutating state                                                                   |
| `generate_pr_summary` | PR-friendly markdown or JSON summary                                                                                 |

### Step 4: Focused Checks

Narrow queries over a single quality dimension. Cheaper than `list_findings`
when you know which dimension to inspect.

| Tool               | Dimension                      |
|--------------------|--------------------------------|
| `check_clones`     | Clone groups                   |
| `check_complexity` | Cyclomatic complexity hotspots |
| `check_coupling`   | Afferent/efferent coupling     |
| `check_cohesion`   | Module cohesion                |
| `check_dead_code`  | Dead code candidates           |
