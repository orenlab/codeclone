---
name: codeclone-review
description: Use when Codex should review a Python repository through CodeClone MCP — conservative first pass, baseline-aware triage, changed-files review, or deeper exploratory follow-up.
---

# CodeClone Review

Use this skill for structural review, clone triage, changed-scope review, or
health-oriented refactor planning in a Python repository.

## Rules

- Use MCP tools only when invoked through the CodeClone plugin.
- If no latest MCP run exists, call `analyze_repository` or `analyze_changed_paths` yourself before reading `latest/*` resources.
- Start with the default or `pyproject`-resolved CodeClone profile.
- Do not lower thresholds on the first pass.
- Lower-threshold runs are explicit exploratory follow-ups, not silent replacements.
- Prefer production-first and changed-files-first review over broad listing.
- CodeClone is the source of truth — do not reinterpret findings independently.
- Do not fall back to CLI or local report files.
- Never auto-suppress findings or mutate repository state.

## Workflows

### Full repository

```
analyze_repository → get_production_triage
→ list_hotspots → get_finding → get_remediation
```

### Changed files (PR / patch)

```
analyze_changed_paths → get_report_section(section="changed")
→ list_findings(changed_paths=..., sort_by="priority") → generate_pr_summary
```

### Gate preview

```
analyze_repository → evaluate_gates
→ explain reasons, do not change files
```

### Current-run metrics and coverage surfaces

```
analyze_repository → get_report_section(section="metrics")
```

If the question is about external Cobertura join semantics:

1. Call `help(topic="coverage")`.
2. Explain `coverage_hotspots` vs `scope_gap_hotspots` from canonical metrics.
3. Do not turn scope gaps into "untested" claims.

### Deeper follow-up

If the default pass looks clean:

1. Call `help(topic="analysis_profile")` for threshold semantics.
2. Run a second analysis with lower thresholds.
3. Explain this is a higher-sensitivity pass with more noise.
4. Use `compare_runs` to show the delta.

## Tool preferences

- Prefer `list_hotspots` or `check_*` before broad `list_findings`.
- For finding/list/check tools, use `detail_level="summary"`, `"normal"`, or
  `"full"` only. `compact` is valid only for `help(detail="compact")`.
- Use `get_finding` / `get_remediation` for one finding — not `detail_level=full` on lists.
- Use `"production-only"` / `source_kind` filters to cut test noise.
- Use `get_report_section(section="metrics")` for adoption, API-surface, or Coverage Join facts.
- Use `mark_finding_reviewed` + `exclude_reviewed=true` in long sessions.
- Pass absolute `root` — MCP rejects relative roots.

## Non-goals

- Do not auto-suppress findings.
- Do not treat report-only `overloaded_modules` as findings or gate data.
- Do not present a clean default pass as proof that no finer-grained issues exist.
