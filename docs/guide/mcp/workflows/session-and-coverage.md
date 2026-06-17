<!-- doc-scope: MCP session tools. class: guide max-lines: 120 -->

# Coverage join & session review markers

Two **optional** MCP workflows that most agents skip on the first pass:

1. **Coverage Join** — attach an external Cobertura XML from your test run and
   preview untested-hotspot gating.
2. **Session review markers** — track which findings you already triaged inside
   one long MCP process.

Start with [Analyze & triage](analyze-and-triage.md) for health checks and PR
review. Use this page when you already have a coverage artifact or a long
finding backlog in the same chat session.

Normative tool shapes:
[session tools](../../../book/25-mcp-interface/tools/session-and-memory.md),
[analysis & gates](../../../book/25-mcp-interface/tools/analysis.md),
[Coverage Join config](../../../book/10-config-and-defaults.md).

## Coverage Join (Cobertura + gates)

Join measured coverage to function hotspots for the **current run only**. Coverage
Join does not update baseline, cache, or canonical report persistence.

| Requirement | Detail |
|-------------|--------|
| Analysis mode | `analysis_mode="full"` — `coverage_xml` is rejected in `clones_only` |
| Input | Cobertura XML path on `analyze_repository` (`coverage_xml`) |
| Typical follow-up | `get_report_section(section="metrics_detail", family="coverage_join")` |
| Gate preview | `evaluate_gates(fail_on_untested_hotspots=true, coverage_min=50)` |

```
analyze_repository(root=<abs>, coverage_xml="coverage.xml")
  -> get_report_section(section="metrics_detail", family="coverage_join")
  -> evaluate_gates(fail_on_untested_hotspots=true, coverage_min=50)
```

!!! tip "CLI equivalent"
    `codeclone --coverage coverage.xml --fail-on-untested-hotspots` uses the same
    join semantics. MCP `evaluate_gates` previews exit reasons without mutating
    repository state.

## Session review loop (in-memory markers)

MCP keeps run snapshots and **session-local** reviewed markers in the server
process. They survive across tool calls but disappear on process restart — not
Engineering Memory, not baseline truth.

Use when triaging many findings in one agent session: mark handled items, then
filter them out on the next pass.

| Tool | Purpose |
|------|---------|
| `mark_finding_reviewed` | Mark one finding reviewed (optional `note`) |
| `list_findings(exclude_reviewed=true)` | Omit findings already marked in this session |
| `list_reviewed_findings` | List markers for audit |
| `clear_session_runs` | Reset in-memory runs, markers, and workspace intent registry |

```
list_findings
  -> get_finding -> mark_finding_reviewed
  -> list_findings(exclude_reviewed=true) -> ...
  -> clear_session_runs   # full session reset — also clears active intents
```

For durable facts across sessions, use [Memory recipes](memory-recipes.md)
instead of review markers.

---
