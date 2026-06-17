---
name: codeclone-implementation-context
description: get_implementation_context — bounded structural, call-graph, contract, memory-lane, and change-control evidence from ONE stored MCP run. Read-only; never grants edit permission.
---

# CodeClone Implementation Context

Projects bounded, deterministic evidence from ONE stored
`analyze_repository` / `analyze_changed_paths` run (canonical report + off-report
symbol index, relationship facts, freshness). Does NOT re-analyze, mutate state, or
grant edit permission.

## When to use

| Situation                            | Call                                                                  |
|--------------------------------------|-----------------------------------------------------------------------|
| Orient before declaring intent       | `paths=[...]`, `mode="implementation"`                                |
| Inside an edit cycle (after `start`) | `paths=[...]` + `intent_id` → adds `change_control`                   |
| Transitive / baseline-aware planning | `mode="impact"` (callers, baseline-sensitive findings)                |
| Contract / schema work               | `mode="contract"` (definition sites, version constants)               |
| Function call graph                  | `symbols=["pkg.mod:func"]` + `include=["callers","callees"]`          |
| Name / usage search                  | `query="name"` — defs + call targets + imports, incl. external/stdlib |
| Current WIP without listing paths    | `changed_scope=true` (never with `paths`/`symbols`)                   |

## Subject resolution (in order)

1. explicit `paths` and/or `symbols`; 2. active intent `allowed_files` (with
   `intent_id`, no explicit subject); 3. live git-dirty set (`changed_scope=true`);
4. else `status:"no_current_work"` — whole-repo context is NEVER inferred.

Symbols use a COLON: `module:symbol` (`pkg.mod:func`). Dot notation does not resolve →
`unresolved_symbols`. A symbol-only query resolving nothing → `subject_not_found`.

## Hard rules — MUST / MUST NOT

- MUST NOT treat `edit_allowed` here as authorization. It MIRRORS `start_controlled_change`. Only `start` grants edits;
  this tool never changes permission.
- MUST NOT skip `get_relevant_memory` (change-control step 3) because a memory lane appeared here — that lane is
  orientation, not governance.
- MUST NOT treat unresolved call edges (`target_qualname: null`) as resolved facts.
- MUST NOT treat a `*_summary.truncated: true` collection as complete, or `not_available` as "none exist".
- MUST NOT use context output to widen declared scope or override `do_not_touch`.
- `do_not_touch` = hard boundary; `review_context` = advisory; `clone_cohort_members` = comparison, not edit targets.
- `freshness.status="drifted"` in a shared worktree → verify conclusions against source; do NOT re-analyze in a loop.
  Re-analyze once, at verification boundaries.

## Reading the response

> Key / easily-misread fields; the real response carries more.

| Field                                                   | Meaning                                                                             |
|---------------------------------------------------------|-------------------------------------------------------------------------------------|
| `status`                                                | ok / subject_not_found / no_current_work / needs_analysis / safety_context_overflow |
| `analysis.freshness.status`                             | fresh / drifted (re-analyze before relying)                                         |
| `analysis.call_graph_status`                            | complete / partial / unavailable — if partial, read `uncertainties`                 |
| `subject.resolved_symbols` / `unresolved_symbols`       | exact file:line / unknown qualnames (never guessed)                                 |
| `change_control.edit_allowed`                           | MIRROR of start — not a grant                                                       |
| `*_summary.{truncated,omitted}`                         | collection is bounded — not full coverage                                           |
| `context_artifact_digest` / `context_projection_digest` | run+artifact binding / request+response binding                                     |

## Non-goals

- Do not declare intent or finish verification (use `codeclone-change-control`).
- Do not replace `get_relevant_memory` in the edit pipeline.
- Do not auto-fix from context results. Do not force a freshness race in shared worktrees.
- Do not fall back to CLI or local report files.
