---
name: codeclone-review
description: Use when Codex should review a Python repository through CodeClone MCP with a conservative first pass, baseline-aware triage, changed-files review, or a deeper exploratory follow-up.
---

# CodeClone Review

Use this skill when the task is structural review, clone triage, changed-scope
review, or health-oriented refactor planning in a Python repository.

## Core rules

- Start with the default or `pyproject`-resolved CodeClone profile.
- Do not lower thresholds on the first pass.
- Treat lower-threshold runs as explicit exploratory follow-ups, not as a silent
  replacement for the conservative default profile.
- Prefer production-first and changed-files-first review over broad listing.
- Keep CodeClone as the source of truth. Do not invent a second analyzer or
  reinterpret findings independently.

## First-pass workflows

### Full repository review

1. Run `analyze_repository`.
2. Read `get_run_summary` or `get_production_triage`.
3. Use `list_hotspots` or focused `check_*` tools before broad `list_findings`.
4. Open one finding with `get_finding` or `get_remediation` only when needed.

### Changed-files review

1. Run `analyze_changed_paths`.
2. Read `get_report_section(section="changed")` or `get_production_triage`.
3. Focus on changed-scope findings first.

## Deeper exploratory follow-up

If the default pass looks clean but the user wants smaller local repetition:

1. Call `help(topic="analysis_profile")` if thresholds or semantics are unclear.
2. Run a second analysis with lower thresholds.
3. Explain that the second pass is higher-sensitivity and may increase noise.
4. Keep comparisons profile-aware.

## Prompt shaping

Prefer prompts that explicitly name:

- repository-wide review vs changed-files review
- production hotspots vs all findings
- default conservative pass vs deeper exploratory follow-up

## Non-goals

- Do not auto-suppress findings.
- Do not treat report-only `overloaded_modules` as findings or gate data.
- Do not present a clean default pass as proof that no finer-grained repetition
  exists.
