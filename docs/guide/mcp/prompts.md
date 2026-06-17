<!-- doc-scope: MCP prompt patterns. class: guide max-lines: 120 -->

# MCP prompt patterns

## Prompt patterns

Good prompts include **scope**, **goal**, and **constraint**:

```text title="Health check"
Use codeclone MCP to analyze this repository.
Give me a concise structural health summary and the top findings to look at first.
```

```text title="Changed-files review"
Use codeclone MCP in changed-files mode for my latest edits.
Focus only on findings that touch changed files and rank them by priority.
```

```text title="Gate preview"
Run codeclone through MCP and preview gating with fail_on_new.
Explain the exact reasons. Do not change any files.
```

```text title="AI-generated code check"
I added code with an AI agent. Use codeclone MCP to check for new structural drift.
Separate accepted baseline debt from patch-local before/after regressions.
```

!!! tip "Best practices"

    - Use `analyze_changed_paths` for PRs, not full analysis.
    - Prefer `get_run_summary` or `get_production_triage` as the first pass.
    - Prefer `list_hotspots` or narrow `check_*` tools before broad `list_findings`.
    - Use `get_finding` / `get_remediation` for one finding instead of raising
      `detail_level` on larger lists.
    - Pass an absolute `root` — MCP rejects relative roots like `.`.
    - Use `coverage_xml` only with `analysis_mode="full"`.
    - Use `source_kind="production"` (or `tests`, `fixtures`, `mixed`, `other`) to
      cut test/fixture noise.
    - Use `mark_finding_reviewed` + `exclude_reviewed=true` in long sessions.

---
