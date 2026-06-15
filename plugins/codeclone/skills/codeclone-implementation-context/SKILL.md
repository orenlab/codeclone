---
name: codeclone-implementation-context
description: Use get_implementation_context for bounded structural, call-graph, contract, memory-lane, and change-control evidence from one stored MCP run — when to call it, subject and mode rules, edit-cycle sequence, and hard non-goals.
---

# CodeClone Implementation Context

Use `get_implementation_context` to project **bounded, deterministic evidence** from
**one stored** `analyze_repository` / `analyze_changed_paths` run. The tool reads
the canonical report plus off-report context artifacts (symbol index, relationship
facts, freshness delta). It does **not** re-analyze, mutate repository state, or
grant edit permission.

Full contract: `help(topic="implementation_context")` and
`docs/book/25-mcp-interface/tools/analysis.md`.

## When to use

| Situation                              | Call pattern                                                                       |
|----------------------------------------|------------------------------------------------------------------------------------|
| After analyze, before declaring intent | `paths=[...]`, `mode="implementation"` — imports, API surface, callees, blast zone |
| Inside an edit cycle, after `start`    | same `paths` + `intent_id` + before-run `run_id` — adds `change_control` block     |
| Transitive / baseline-aware planning   | `mode="impact"` — callers, baseline-sensitive findings, review context             |
| Contract / schema work                 | `mode="contract"` — definition sites, version constants, D18-gated path callers    |
| Function-level call graph              | `symbols=["pkg.mod:func"]` + `include=["callers","callees"]`                       |
| Current WIP without listing paths      | `changed_scope=true` (never combine with `paths` or `symbols`)                     |

## When NOT to use

- **No stored run** — call `analyze_repository` or `analyze_changed_paths` first.
- **Edit permission** — only `start_controlled_change` returns `edit_allowed`; this tool
  mirrors it when `intent_id` is passed but never creates permission.
- **Whole-repo triage** — use `get_production_triage`, `list_hotspots`, or `list_findings`.
- **Memory governance alone** — change-control still requires `get_relevant_memory`
  (step 3); context tool complements, does not replace it.
- **Blast-only inspection** — use `get_blast_radius` when you need only blast fields
  without bundling call_context, memory lanes, or freshness (advanced/diagnostic).
- **Stale run** — if `analysis.freshness.status` is `drifted`, re-analyze before
  relying on the projection.

## Prerequisites

1. Valid MCP run for the same absolute `root`.
2. Repo-relative `paths` inside the root, and/or `module:symbol` qualnames.
3. Optional active `intent_id` from `start_controlled_change` (pins run + adds
   `change_control`).

## Sequences

### A. Read-only reconnaissance (no intent)

```
analyze_repository(root=abs)
→ get_implementation_context(root=abs, paths=["pkg/mod.py"], mode="implementation")
```

Use before `start` to choose scope and spot dependents / callees.

### B. Normal edit cycle (with intent)

```
1. analyze_repository(root=abs)                    # before-run
2. start_controlled_change(...)
3. get_relevant_memory(root=abs, intent_id=...)    # still required — see engineering-memory skill
4. get_implementation_context(
     root=abs,
     paths=[...],                                 # files you will edit
     intent_id=...,
     run_id=<before-run id>,
     mode="implementation",
   )
5. edit inside declared scope only
6. analyze_repository → finish_controlled_change
```

Pass the **same before-run** `run_id` as the intent; do not redeclare intent on
the after-run.

### C. Impact or contract follow-up

```
get_implementation_context(..., mode="impact")     # transitive blast + callers + baseline findings
get_implementation_context(..., mode="contract")   # contracts{} truth-map
```

`depth > 1` or `mode="impact"` uses transitive blast projection.

## Subject rules (code contract)

**Resolution order** when `paths` / `symbols` are omitted:

1. explicit `paths` and/or `symbols`;
2. active intent `allowed_files` (with `intent_id`, no explicit subject);
3. bounded live git-dirty set (`changed_scope=true` forces dirty set);
4. else `status="no_current_work"` — whole-repo context is never inferred.

**Symbols:** `module:symbol` with a **colon** (for example `pkg.mod:func`). Dot
notation (`pkg.mod.func`) is rejected → `subject.unresolved_symbols`. Inspect
`subject.resolved_symbols` and `subject.unresolved_symbols`; never guess.

**Symbol-scoped call graph:** explicit symbol subjects limit `call_context` to
resolved symbols only — not every function in the same file.

**Intent overlay:** with `intent_id`, `change_control` carries `allowed_files`,
`do_not_touch`, `review_context`, `guards`, and `edit_allowed` (mirror of start).
`review_context` is **not** duplicated in `structural_context` when intent is present.

## Modes and `include`

| `mode`           | Default facets (abbrev.)                                                                       |
|------------------|------------------------------------------------------------------------------------------------|
| `implementation` | module_role, imports, importers, callees, public_surface, blast_radius, tests, docs, memory    |
| `impact`         | blast_radius, importers, callers, baseline_sensitive_findings, review_context, memory, …       |
| `contract`       | definition_sites, version_constants, contract_tests, persistence/serialization path callers, … |

With `intent_id` and default `include`, `scope` is added automatically. Pass
`include=[...]` to request a closed facet set; unknown facet → contract error.

Memory-backed facets (`memory`, `docs`, `trajectories`, `experiences`, `tests`,
`contract_tests`, `memory_conflicts`) load the memory store when requested.
`trajectories` / `experiences` work **without** `include=["memory"]`.

## Reading the response

| Block                      | Use                                                                            |
|----------------------------|--------------------------------------------------------------------------------|
| `structural_context`       | related_modules, blast_radius summary, module facts                            |
| `call_context`             | callers, callees, references, test_callers — production vs test lanes separate |
| `contracts`                | contract-mode truth-map (`mode="contract"`)                                    |
| `implementation_evidence`  | memory, docs, trajectories, experiences, test_anchors                          |
| `change_control`           | intent boundaries — only with `intent_id`                                      |
| `analysis.freshness`       | `drifted` → re-analyze                                                         |
| `budget_summary`           | one global cap (hard max 200); safety rows consume budget first                |
| `dataflow`                 | always `not_available` — deferred tier, not a bug                              |
| `contracts.*_path_callers` | `not_available` / `no_typed_or_memory_anchor` without D18 anchor               |

Always read each collection's `*_summary` (`truncated`, `omitted`) before claiming
completeness.

## Safety semantics (do not collapse)

| Field                  | Meaning                                                           |
|------------------------|-------------------------------------------------------------------|
| `do_not_touch`         | **Hard boundary** — separate approval or scope expansion required |
| `review_context`       | **Advisory** — review before editing; not a ban                   |
| `clone_cohort_members` | Comparison context — not automatic edit targets                   |

`start` blast summary and live `get_implementation_context` may differ when query
**subject** ≠ declared intent scope or the tree drifted after start. Prefer live
`get_implementation_context` with `intent_id` + explicit `paths` before editing.

## Digests

- `context_artifact_digest` — binds the off-report artifact to the run.
- `context_projection_digest` — binds this request's bounded response.

Cite digests when recording review evidence; they do not authorize edits.

## Rules

- Use MCP tools only when invoked through the CodeClone plugin.
- Pass absolute `root`; MCP rejects relative roots.
- CodeClone is the source of truth — do not reinterpret findings.
- Do not fall back to CLI or local report files.
- Do not treat unresolved call edges (`target_qualname: null`) as resolved facts.
- Do not treat `not_available` contract or dataflow facets as "no callers exist".
- Do not treat truncated collections as complete without reading `*_summary`.
- Do not use context output to expand declared scope or override `do_not_touch`.

## Non-goals

- Declare intent or finish verification — use `codeclone-change-control`.
- Replace `get_relevant_memory` in the mandatory edit pipeline.
- Replace `get_blast_radius` when blast-only fields suffice.
- Auto-fix or edit files based on context results.
