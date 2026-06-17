## CLI Controller Queries

The CLI exposes read-only terminal projections for humans:

```bash
codeclone . --blast-radius codeclone/analysis/parser.py
codeclone . --patch-verify
codeclone . --patch-verify --strictness relaxed
codeclone . --session-stats
codeclone . --audit
codeclone . --audit-json
```

For git-scoped clone review (not patch-verify), use changed-scope flags instead:

```bash
codeclone . --changed-only --diff-against HEAD~1
```

`--blast-radius` runs normal analysis, builds the canonical report in memory,
and renders the same dependent/context split as `get_blast_radius`.

`--patch-verify` is a baseline-relative terminal check: it uses the trusted
clone baseline as the accepted comparison snapshot and checks baseline-relative
new clone regressions plus the selected gate profile. It is not the same as MCP
patch-local verification, which compares a clean before-run to an after-run.
`ci` is the default; `strict` applies tighter controller budgets; `relaxed`
reports violations but exits `0`.

Controller query modes cannot combine with changed-scope flags
(`--changed-only`, `--diff-against`, `--paths-from-git-diff`). Combining
`--patch-verify` with `--diff-against` is a contract error — pick one workflow.

`--session-stats` shows workspace session status: active agents, intents, and
lease health. Read-only, does not run analysis. Collection is implemented in
`codeclone/controller_insights/session_stats.py` (CLI and IDE-only MCP tools
consume the same payload).

`--audit` and `--audit-json` show the local Controller audit trail (JSON footprint
mode for `--audit-json`). Both require `audit_enabled=true` in effective config.
`--audit-json` selects JSON output but does not set the `--audit` flag for
combination validation.

### Flag combination rules

Enforced by `codeclone/surfaces/cli/workflow.py:_validate_controller_query_flags`:

| Combination                                                               | Result         |
|---------------------------------------------------------------------------|----------------|
| `--blast-radius` + `--patch-verify`                                       | contract error |
| `--session-stats` + explicit `--audit`                                    | contract error |
| `--session-stats` + `--blast-radius` or `--patch-verify`                  | contract error |
| explicit `--audit` + `--blast-radius` or `--patch-verify`                 | contract error |
| any controller query + changed-scope flags                                | contract error |
| any controller query + report output flags                                | contract error |
| any controller query + baseline update flags                              | contract error |
| `--strictness` without `--patch-verify` (when `--strictness` is explicit) | contract error |

`--audit-json` is not treated as `--audit` for the session-stats mutual-exclusion
check. Pre-analysis queries (`--session-stats`, `--audit`, `--audit-json`) exit
before analysis; only one runs per invocation (first match wins).

CLI controller queries are terminal-only and read-only with respect to source
files, baselines, reports, and analysis cache data. They are incompatible with
report output flags and baseline update flags.
