# MCP Usage Guide

CodeClone MCP is a **read-only, baseline-aware** analysis server for AI agents
and MCP-capable clients. It exposes the existing deterministic pipeline as tools
and resources — no separate analysis engine, no source mutation, no baseline
writes.

MCP is a **client integration surface**, not a model-specific feature. It works
with any MCP-capable client regardless of the backend model.

## Install

```bash
pip install "codeclone[mcp]"        # add MCP extra
# or
uv tool install "codeclone[mcp]"    # install as a standalone tool
```

## Start the server

**Local agents** (Claude Code, Codex, Copilot Chat, Gemini CLI):

```bash
codeclone-mcp --transport stdio
```

**Remote / HTTP-only clients:**

```bash
codeclone-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Non-loopback hosts require `--allow-remote` (no built-in auth).
Run retention is bounded: default `4`, max `10` (`--history-limit`).
If a tool request omits `processes`, MCP defers process-count policy to the
core CodeClone runtime.

## Tool surface

| Tool                     | Purpose                                                                                              |
|--------------------------|------------------------------------------------------------------------------------------------------|
| `analyze_repository`     | Full analysis → register as latest run                                                               |
| `analyze_changed_paths`  | Diff-aware analysis with `changed_paths` or `git_diff_ref`; summary inventory is slimmed to counts   |
| `get_run_summary`        | Compact health/findings/baseline snapshot with slim inventory counts                                 |
| `get_production_triage`  | Compact production-first view: health, cache freshness, production hotspots, production suggestions  |
| `compare_runs`           | Regressions, improvements, health delta between two runs                                             |
| `list_findings`          | Filtered, paginated finding groups with envelope-level `base_uri`                                    |
| `get_finding`            | Deep inspection of one finding by id                                                                 |
| `get_remediation`        | Structured remediation payload for one finding                                                       |
| `list_hotspots`          | Derived views: highest priority, production hotspots, spread, etc., with compact summary cards       |
| `get_report_section`     | Read canonical report sections; `metrics` is summary-only, `metrics_detail` is the full metrics dump |
| `evaluate_gates`         | Preview CI/gating decisions without exiting                                                          |
| `check_clones`           | Clone findings from a stored run                                                                     |
| `check_complexity`       | Complexity hotspots from a stored run                                                                |
| `check_coupling`         | Coupling hotspots from a stored run                                                                  |
| `check_cohesion`         | Cohesion hotspots from a stored run                                                                  |
| `check_dead_code`        | Dead-code findings from a stored run                                                                 |
| `generate_pr_summary`    | PR-friendly markdown or JSON summary                                                                 |
| `mark_finding_reviewed`  | Session-local review marker (in-memory only)                                                         |
| `list_reviewed_findings` | List reviewed findings for a run                                                                     |
| `clear_session_runs`     | Reset all in-memory runs and session caches                                                          |

> `check_*` tools query stored runs only. Call `analyze_repository` or
> `analyze_changed_paths` first.

`check_*` responses keep `health.score` and `health.grade`, but slim
`health.dimensions` down to the one dimension relevant to that tool.
List-style finding responses also expose `base_uri` once per envelope and keep
summary locations as `file` + `line`; richer `symbol` / `uri` data stays in
`normal` / `full` responses and `get_finding`. Summary-style MCP cache payloads
also expose `effective_freshness` (`fresh`, `mixed`, `reused`).
Inline design-threshold parameters on `analyze_repository` /
`analyze_changed_paths` become part of the canonical run: they are recorded in
`meta.analysis_thresholds.design_findings` and define that run's canonical
design findings.

## Resource surface

Fixed resources:

| Resource                         | Content                                    |
|----------------------------------|--------------------------------------------|
| `codeclone://latest/summary`     | Latest run summary                         |
| `codeclone://latest/triage`      | Latest production-first triage             |
| `codeclone://latest/report.json` | Full canonical report                      |
| `codeclone://latest/health`      | Health score and dimensions                |
| `codeclone://latest/gates`       | Last gate evaluation result                |
| `codeclone://latest/changed`     | Changed-files projection (diff-aware runs) |
| `codeclone://schema`             | Canonical report shape descriptor          |

Run-scoped resource templates:

| URI template                                      | Content                         |
|---------------------------------------------------|---------------------------------|
| `codeclone://runs/{run_id}/summary`               | Summary for a specific run      |
| `codeclone://runs/{run_id}/report.json`           | Report for a specific run       |
| `codeclone://runs/{run_id}/findings/{finding_id}` | One finding from a specific run |

Resources and URI templates are read-only views over stored runs; they do not
trigger analysis.

`codeclone://latest/*` always resolves to the most recent run registered in the
current MCP server session. A later `analyze_repository` or
`analyze_changed_paths` call moves that pointer.

## Recommended workflows

### Full repository review

```
analyze_repository → get_production_triage → get_finding → evaluate_gates
```

### Changed-files review (PR / patch)

```
analyze_changed_paths → get_report_section(section="changed")
→ list_findings(changed_paths=..., sort_by="priority") → get_remediation → generate_pr_summary
```

### Session-based review loop

```
list_findings → get_finding → mark_finding_reviewed
→ list_findings(exclude_reviewed=true) → … → clear_session_runs
```

## Prompt patterns

Good prompts include **scope**, **goal**, and **constraint**:

### Health check

```text
Use codeclone MCP to analyze this repository. Give me a concise structural health summary
and explain which findings are worth looking at first.
```

### Clone triage (production only)

```text
Analyze through codeclone MCP, filter to clone findings in production code only,
and show me the top 3 clone groups worth fixing first.
```

### Changed-files review

```text
Use codeclone MCP in changed-files mode for my latest edits.
Focus only on findings that touch changed files and rank them by priority.
```

### Dead-code review

```text
Use codeclone MCP to review dead-code findings. Separate actionable items from
likely framework false positives. Do not add suppressions automatically.
```

### Gate preview

```text
Run codeclone through MCP and preview gating with fail_on_new plus a zero clone threshold.
Explain the exact reasons. Do not change any files.
```

### AI-generated code check

```text
I added code with an AI agent. Use codeclone MCP to check for new structural drift:
clone groups, dead code, duplicated branches, design hotspots.
Separate accepted baseline debt from new regressions.
```

### Safe refactor planning

```text
Use codeclone MCP to pick one production finding that looks safe to refactor.
Explain why it is a good candidate and outline a minimal plan.
```

### Run comparison

```text
Compare the latest CodeClone MCP run against the previous one.
Show regressions, resolved findings, and health delta.
```

**Tips:**

- Use `analyze_changed_paths` for PRs, not full analysis.
- Set `cache_policy="off"` when you need the freshest truth from a new analysis
  run, not whatever older session state currently sits behind `latest/*`.
- Use `"production-only"` / `source_kind` filters to cut test/fixture noise.
- Use `mark_finding_reviewed` + `exclude_reviewed=true` in long sessions.
- Ask the agent to separate baseline debt from new regressions.

## Client configuration

All clients use the same CodeClone server — only the registration differs.

### Claude Code / Anthropic

```json
{
  "mcpServers": {
    "codeclone": {
      "command": "codeclone-mcp",
      "args": [
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### Codex / OpenAI (command-based)

```toml
[mcp_servers.codeclone]
enabled = true
command = "codeclone-mcp"
args = ["--transport", "stdio"]
```

For the Responses API or remote-only OpenAI clients, use `streamable-http`.

### GitHub Copilot Chat

```json
{
  "mcpServers": {
    "codeclone": {
      "command": "codeclone-mcp",
      "args": [
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### Gemini CLI

Same `stdio` registration. If the client only accepts remote URLs, use
`streamable-http` and point to the `/mcp` endpoint.

### Other clients

- `stdio` for local analysis
- `streamable-http` for remote/HTTP-only clients

If `codeclone-mcp` is not on `PATH`, use an absolute path to the launcher.

## Security

- Read-only by design: no source mutation, no baseline/cache writes.
- Run history and review markers are in-memory only — lost on process stop.
- Repository access is limited to what the server process can read locally.
- `streamable-http` binds to loopback by default; `--allow-remote` is explicit opt-in.

## Troubleshooting

| Problem                                                   | Fix                                                                            |
|-----------------------------------------------------------|--------------------------------------------------------------------------------|
| `CodeClone MCP support requires the optional 'mcp' extra` | `pip install "codeclone[mcp]"`                                                 |
| Client cannot find `codeclone-mcp`                        | `uv tool install "codeclone[mcp]"` or use absolute path                        |
| Client only accepts remote MCP                            | Use `streamable-http` transport                                                |
| Agent reads stale results                                 | Call `analyze_repository` again; `latest` always points to the most recent run |
| `changed_paths` rejected                                  | Pass a `list[str]` of repo-relative paths, not a comma-separated string        |

## See also

- [book/20-mcp-interface.md](book/20-mcp-interface.md) — formal interface contract
- [book/08-report.md](book/08-report.md) — canonical report contract
- [book/09-cli.md](book/09-cli.md) — CLI reference
