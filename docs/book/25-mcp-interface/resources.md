## Resources

Resources are deterministic read-only projections over stored runs. They do
not trigger analysis.

### Fixed resources

| URI                              | Content                                                   |
|----------------------------------|-----------------------------------------------------------|
| `codeclone://latest/summary`     | Compact summary for the latest stored run                 |
| `codeclone://latest/report.json` | Canonical JSON report for the latest stored run           |
| `codeclone://latest/health`      | Health/metrics snapshot                                   |
| `codeclone://latest/gates`       | Last gate-evaluation result                               |
| `codeclone://latest/changed`     | Changed-files projection                                  |
| `codeclone://latest/triage`      | Production-first triage payload                           |
| `codeclone://latest/overview`    | Highest-spread hotspot overview for the latest stored run |
| `codeclone://schema`             | Canonical report shape descriptor                         |

`summary`, `report.json`, `health`, `gates`, `changed`, `triage`, and `schema`
are advertised by the MCP server resource catalog. `overview` is a supported
`read_resource` URI for clients that request it directly.

### Run-scoped templates

| URI template                                      | Content                                            |
|---------------------------------------------------|----------------------------------------------------|
| `codeclone://runs/{run_id}/summary`               | Summary for a specific run                         |
| `codeclone://runs/{run_id}/report.json`           | Report for a specific run                          |
| `codeclone://runs/{run_id}/overview`              | Highest-spread hotspot overview for a specific run |
| `codeclone://runs/{run_id}/findings/{finding_id}` | One finding from a specific run                    |

The advertised template catalog includes `summary`, `report.json`, and
`findings/{finding_id}`. The run-scoped `overview` suffix is supported by the
service reader for direct requests.

`codeclone://latest/*` always resolves to the most recent run.

---
