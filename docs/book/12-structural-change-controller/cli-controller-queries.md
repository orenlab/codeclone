## CLI Controller Queries

The CLI exposes read-only terminal projections for humans:

```bash
codeclone . --blast-radius codeclone/analysis/parser.py
codeclone . --patch-verify --diff-against HEAD~1
codeclone . --patch-verify --strictness relaxed
codeclone . --session-stats
```

`--blast-radius` runs normal analysis, builds the canonical report in memory,
and renders the same dependent/context split as `get_blast_radius`.

`--patch-verify` is a baseline-relative terminal check: it uses the trusted
clone baseline as the accepted comparison snapshot and checks baseline-relative
new clone regressions plus the selected gate profile. It is not the same as MCP
patch-local verification, which compares a clean before-run to an after-run.
`ci` is the default; `strict` applies tighter controller budgets; `relaxed`
reports violations but exits `0`.

`--session-stats` shows workspace session status: active agents, intents, and
lease health. Read-only, does not run analysis. Collection is implemented in
`codeclone/controller_insights/session_stats.py` (CLI and IDE-only MCP tools
consume the same payload).

CLI controller queries are terminal-only and read-only with respect to source
files, baselines, reports, and analysis cache data. They are incompatible with
report output flags and baseline update flags.
