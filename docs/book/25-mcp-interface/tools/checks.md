### Focused check tools

| Tool               | Key parameters                                                                         | Purpose                  |
|--------------------|----------------------------------------------------------------------------------------|--------------------------|
| `check_clones`     | `run_id` or `root`, `path`, `clone_type`, `source_kind`, `max_results`, `detail_level` | Narrow clone-only query  |
| `check_complexity` | `run_id` or `root`, `path`, `min_complexity`, `max_results`, `detail_level`            | Complexity hotspot query |
| `check_coupling`   | `run_id` or `root`, `path`, `max_results`, `detail_level`                              | Coupling hotspot query   |
| `check_cohesion`   | `run_id` or `root`, `path`, `max_results`, `detail_level`                              | Cohesion hotspot query   |
| `check_dead_code`  | `run_id` or `root`, `path`, `min_severity`, `max_results`, `detail_level`              | Dead code query          |
