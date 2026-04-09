# MCP Usage Guide

CodeClone MCP is a **read-only, baseline-aware** analysis server for AI agents
and MCP-capable clients. It exposes the deterministic pipeline without mutating
source files, baselines, cache, or report artifacts. Session-local review/run
state is mutable in memory only.

Works with any MCP-capable client regardless of backend model.

## Install

```bash
uv tool install --pre "codeclone[mcp]"    # install as a standalone tool
# or, inside an existing environment
uv pip install --pre "codeclone[mcp]"     # add the MCP extra to that environment
```

## Quick client setup

If `codeclone-mcp` is already on your `PATH`, both Claude Code and Codex can
register it directly as a local stdio server.

### Claude Code

```bash
claude mcp add codeclone -- codeclone-mcp --transport stdio
claude mcp list
```

Use `--scope project` if you want Claude Code to store the shared config in
`.mcp.json` for the repository instead of your local user state.

### Codex

```bash
codex mcp add codeclone -- codeclone-mcp --transport stdio
codex mcp list
```

If you installed CodeClone into a project virtual environment rather than a
global tool path, use the full launcher path instead of bare `codeclone-mcp`.

### Codex plugin

A native Codex plugin ships in `plugins/codeclone/` with repo-local
discovery, a `.mcp.json` definition, and two skills (review + hotspots).
See [Codex plugin guide](codex-plugin.md).

### Claude Desktop bundle

A local `.mcpb` bundle ships in `extensions/claude-desktop-codeclone/` with
pre-loaded instructions and auto-discovery of the launcher.
See [Claude Desktop bundle guide](claude-desktop-bundle.md).

## Start the server

**Local agents** (Claude Code, Codex, Copilot Chat, Gemini CLI):

```bash
codeclone-mcp --transport stdio
```

MCP analysis tools require an absolute repository root. Relative roots such as
`.` are rejected, because the server process working directory may differ from
the client workspace. The same absolute-path rule applies to `check_*` tools
when a `root` filter is provided.

**Remote / HTTP-only clients:**

```bash
codeclone-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Non-loopback hosts require `--allow-remote` (no built-in auth).
When `--allow-remote` is enabled, any reachable network client can trigger
CPU-intensive analysis, read results, and probe repository-relative paths
through MCP request parameters. Use it only on trusted networks. For anything
production-adjacent, put the server behind a firewall or a reverse proxy with
authentication.
Run retention is bounded: default `4`, max `10` (`--history-limit`).
If a tool request omits `processes`, MCP defers process-count policy to the
core CodeClone runtime.

Current `b5` MCP surface: `21` tools, `7` fixed resources, and `3`
run-scoped URI templates.

## Tool surface

| Tool                     | Purpose                                                                                                  |
|--------------------------|----------------------------------------------------------------------------------------------------------|
| `analyze_repository`     | Full analysis → compact summary; use `get_run_summary` or `get_production_triage` as the first pass      |
| `analyze_changed_paths`  | Diff-aware analysis via `changed_paths` or `git_diff_ref`; compact changed-files snapshot                |
| `get_run_summary`        | Cheapest run snapshot: health, findings, baseline, inventory, active thresholds                          |
| `get_production_triage`  | Production-first view: health, hotspots, suggestions, active thresholds; best first pass for noisy repos |
| `help`                   | Semantic guide for workflow, analysis profile, baseline, suppressions, review state, changed-scope       |
| `compare_runs`           | Run-to-run delta: regressions, improvements, health change                                               |
| `list_findings`          | Filtered, paginated findings; use after hotspots or `check_*`                                            |
| `get_finding`            | Single finding detail by id; defaults to `normal` detail level                                           |
| `get_remediation`        | Remediation payload for one finding                                                                      |
| `list_hotspots`          | Priority-ranked hotspot views; preferred before broad listing                                            |
| `get_report_section`     | Read report sections; `metrics_detail` is paginated with family/path filters                             |
| `evaluate_gates`         | Preview CI gating decisions                                                                              |
| `check_clones`           | Clone findings only; narrower than `list_findings`                                                       |
| `check_complexity`       | Complexity hotspots only                                                                                 |
| `check_coupling`         | Coupling hotspots only                                                                                   |
| `check_cohesion`         | Cohesion hotspots only                                                                                   |
| `check_dead_code`        | Dead-code findings only                                                                                  |
| `generate_pr_summary`    | PR-friendly markdown or JSON summary                                                                     |
| `mark_finding_reviewed`  | Session-local review marker (in-memory)                                                                  |
| `list_reviewed_findings` | List reviewed findings for a run                                                                         |
| `clear_session_runs`     | Reset in-memory runs and session state                                                                   |

> `check_*` tools query stored runs only. Call `analyze_repository` or
> `analyze_changed_paths` first.

**Payload conventions:**

- `check_*` responses include only the relevant health dimension.
- Finding responses use short MCP IDs and relative paths by default;
  `detail_level=full` restores the compatibility payload with URIs.
- Summary and triage projections keep interpretation compact: `health_scope`
  explains what the health score covers, `focus` explains the active view, and
  `new_by_source_kind` attributes new findings without widening the payload.
- When baseline comparison is untrusted, summary and triage also expose
  `baseline.compared_without_valid_baseline` plus baseline/runtime python tags.
- Summary `diff` also carries compact adoption/API deltas:
  `typing_param_permille_delta`, `typing_return_permille_delta`,
  `docstring_permille_delta`, `api_breaking_changes`, and `new_api_symbols`.
- Run IDs are 8-char hex handles; finding IDs are short prefixed forms.
  Both accept the full canonical form as input.
- `metrics_detail(family="overloaded_modules")` exposes the report-only
  module-hotspot layer without turning it into findings or gate data.
- `metrics_detail` also accepts `coverage_adoption` and `api_surface`.
- `help(topic=...)` is static: meaning, anti-patterns, next step, doc links.
- Start with repo defaults or `pyproject`-resolved thresholds, then lower them
  only for an explicit higher-sensitivity exploratory pass.

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
`mark_finding_reviewed` and `clear_session_runs` mutate only in-memory session
state. They never touch source files, baselines, cache, or report artifacts.

## Recommended workflows

### Budget-aware first pass

```
analyze_repository → get_run_summary or get_production_triage
→ list_hotspots or check_* → get_finding → get_remediation
```

### Semantic uncertainty recovery

```
help(topic="workflow" | "analysis_profile" | "baseline" | "suppressions" | "latest_runs" | "review_state" | "changed_scope")
```

### Full repository review

```
analyze_repository → get_production_triage
→ list_hotspots(kind="highest_priority") → get_finding → evaluate_gates
```

### Conservative first pass, then deeper review

```
analyze_repository(api_surface=true)     # when you need API inventory/diff
→ help(topic="analysis_profile") when you need finer-grained local review
→ analyze_repository(min_loc=..., min_stmt=..., ...) as an explicit higher-sensitivity pass
→ compare_runs
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

```text
# Health check
Use codeclone MCP to analyze this repository.
Give me a concise structural health summary and the top findings to look at first.

# Changed-files review
Use codeclone MCP in changed-files mode for my latest edits.
Focus only on findings that touch changed files and rank them by priority.

# Gate preview
Run codeclone through MCP and preview gating with fail_on_new.
Explain the exact reasons. Do not change any files.

# AI-generated code check
I added code with an AI agent. Use codeclone MCP to check for new structural drift.
Separate accepted baseline debt from new regressions.
```

**Tips:**

- Use `analyze_changed_paths` for PRs, not full analysis.
- Prefer `get_run_summary` or `get_production_triage` as the first pass.
- Prefer `list_hotspots` or narrow `check_*` tools before broad `list_findings`.
- Use `get_finding` / `get_remediation` for one finding instead of raising
  `detail_level` on larger lists.
- Keep `git_diff_ref` to a safe single revision expression; option-like,
  whitespace-containing, and punctuated shell-style inputs are rejected.
- Pass an absolute `root` — MCP rejects relative roots like `.`.
- Use `"production-only"` / `source_kind` filters to cut test/fixture noise.
- Use `mark_finding_reviewed` + `exclude_reviewed=true` in long sessions.

## Client configuration

All clients use the same server — only the registration format differs.

### JSON clients (Claude Code, Copilot Chat, Gemini CLI)

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

### Codex / OpenAI

```toml
[mcp_servers.codeclone]
enabled = true
command = "codeclone-mcp"
args = ["--transport", "stdio"]
```

For the Responses API or remote-only clients, use `streamable-http`.

If `codeclone-mcp` is not on `PATH`, use an absolute path to the launcher.

## Security

- Read-only by design: no source mutation, no baseline/cache writes.
- Run history and review markers are in-memory only — lost on process stop.
- Repository access is limited to what the server process can read locally.
- `streamable-http` binds to loopback by default; `--allow-remote` is explicit opt-in.

## Troubleshooting

| Problem                                                   | Fix                                                                                 |
|-----------------------------------------------------------|-------------------------------------------------------------------------------------|
| `CodeClone MCP support requires the optional 'mcp' extra` | `uv tool install --pre "codeclone[mcp]"` or `uv pip install --pre "codeclone[mcp]"` |
| Client cannot find `codeclone-mcp`                        | `uv tool install --pre "codeclone[mcp]"` or use an absolute launcher path           |
| Client only accepts remote MCP                            | Use `streamable-http` transport                                                     |
| Agent reads stale results                                 | Call `analyze_repository` again; `latest` always points to the most recent run      |
| `changed_paths` rejected                                  | Pass a `list[str]` of repo-relative paths, not a comma-separated string             |

## See also

- [book/20-mcp-interface.md](book/20-mcp-interface.md) — formal interface contract
- [book/08-report.md](book/08-report.md) — canonical report contract
- [book/09-cli.md](book/09-cli.md) — CLI reference
