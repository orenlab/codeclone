## Resources

Resources are deterministic read-only projections over stored runs. They do
not trigger analysis.

### Fixed resources (7)

| URI                              | Content                                         |
|----------------------------------|-------------------------------------------------|
| `codeclone://latest/summary`     | Compact summary for the latest stored run       |
| `codeclone://latest/report.json` | Canonical JSON report for the latest stored run |
| `codeclone://latest/health`      | Health/metrics snapshot                         |
| `codeclone://latest/gates`       | Last gate-evaluation result                     |
| `codeclone://latest/changed`     | Changed-files projection                        |
| `codeclone://latest/triage`      | Production-first triage payload                 |
| `codeclone://schema`             | Canonical report shape descriptor               |

### Run-scoped templates (3)

| URI template                                      | Content                         |
|---------------------------------------------------|---------------------------------|
| `codeclone://runs/{run_id}/summary`               | Summary for a specific run      |
| `codeclone://runs/{run_id}/report.json`           | Report for a specific run       |
| `codeclone://runs/{run_id}/findings/{finding_id}` | One finding from a specific run |

`codeclone://latest/*` always resolves to the most recent run.

---
