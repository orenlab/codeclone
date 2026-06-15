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

Runtime contract (facets, budgets, response blocks): `help(topic="implementation_context")`
and `docs/book/25-mcp-interface/tools/analysis.md`. This skill teaches **when and
how** to call the tool safely — not every JSON field.

## When to use

| Situation                              | Call pattern                                                                       |
|----------------------------------------|------------------------------------------------------------------------------------|
| After analyze, before declaring intent | `paths=[...]`, `mode="implementation"` — orientation around edit targets           |
| Inside an edit cycle, after `start`    | `paths` + `intent_id` — adds `change_control` (before-run is pinned by intent)     |
| Transitive / baseline-aware planning   | `mode="impact"` — callers, baseline-sensitive findings, review context             |
| Contract / schema work                 | `mode="contract"` — truth-map when reported facets are available                   |
| Function-level call graph              | `symbols=["pkg.mod:func"]` + `include=["callers","callees"]` when graph is complete |
| Current WIP without listing paths      | `changed_scope=true` (never combine with `paths` or `symbols`)                     |

## When NOT to use

- **No stored run** — call `analyze_repository` or `analyze_changed_paths` first.
- **Edit permission** — only `start_controlled_change` returns `edit_allowed`; this tool
  mirrors it when `intent_id` is passed but never creates permission.
- **Whole-repo triage** — use `get_production_triage`, `list_hotspots`, or `list_findings`.
- **Memory governance alone** — change-control still requires `get_relevant_memory`
  (step 3); see **Memory vs governance** below.
- **Blast-only inspection** — use `get_blast_radius` when you need only blast fields
  without bundling call_context, memory lanes, or freshness (advanced/diagnostic).

## Memory vs governance

The memory lane in implementation context is **bounded orientation** around your
subject (docs, trajectories, experiences, test anchors). `get_relevant_memory`
remains the **mandatory governance** step in the edit cycle — retrieval policy,
conflicts, stale records, and contradiction handling. Do not skip step 3 because
context returned a memory block.

## Prerequisites

1. Valid MCP run for the same absolute `root`.
2. Repo-relative `paths` inside the root, and/or `module:symbol` qualnames.
3. Active `intent_id` from `start_controlled_change` when you need `change_control`
   (pins the before-run automatically). Optional `run_id` must match that pinned run
   or the request fails — do not pass the after-run id.

## Sequences

### A. Read-only reconnaissance (no intent)

```
analyze_repository(root=abs)
→ get_implementation_context(root=abs, paths=["pkg/mod.py"], mode="implementation")
```

Use before `start` to choose scope and spot dependents.

### B. Normal edit cycle (with intent)

```
1. analyze_repository(root=abs)                    # before-run
2. start_controlled_change(...)
3. get_relevant_memory(root=abs, intent_id=...)    # required — engineering-memory skill
4. get_implementation_context(
     root=abs,
     paths=[...],
     intent_id=...,
     mode="implementation",
   )
5. edit inside declared scope only
6. analyze_repository(root=abs)                  # after-run when profile requires it
   → finish_controlled_change(..., after_run_id=...)
```

Do not redeclare intent on the after-run. Re-use the **same** `intent_id` on finish.

### C. Impact or contract follow-up

```
get_implementation_context(..., mode="impact")
get_implementation_context(..., mode="contract")
```

`depth > 1` or `mode="impact"` uses transitive blast projection. Check facet
availability in the response — see **Capability gates**.

## Subject rules

**Resolution order** when `paths` / `symbols` are omitted:

1. explicit `paths` and/or `symbols`;
2. active intent `allowed_files` (with `intent_id`, no explicit subject);
3. bounded live git-dirty set (`changed_scope=true` forces dirty set);
4. else `status="no_current_work"` — whole-repo context is never inferred.

**Symbols:** `module:symbol` with a **colon** (for example `pkg.mod:func`). Dot
notation (`pkg.mod.func`) does not resolve → `subject.unresolved_symbols`. Inspect
`subject.resolved_symbols` and `subject.unresolved_symbols`; never guess.

**Symbol-scoped call graph:** explicit symbol subjects limit `call_context` to
resolved symbols only — not every function in the same file.

**Intent overlay:** with `intent_id`, `change_control` carries `allowed_files`,
`do_not_touch`, `review_context`, `guards`, and `edit_allowed` (mirror of start).
`review_context` is **not** duplicated in `structural_context` when intent is present.

When your query **subject** differs from declared intent scope, pass explicit
`paths` plus `intent_id` so boundaries stay aligned with start.

## Mode choice

| `mode`           | Use for                                                          |
|------------------|------------------------------------------------------------------|
| `implementation` | Default edit planning — imports, blast zone, callees, API surface |
| `impact`         | Transitive deps, callers, baseline-sensitive findings            |
| `contract`       | Definition sites, version constants, contract truth-map          |

Default facets per mode, `include` closed sets, and memory-backed facet behavior:
`help(topic="implementation_context")`.

## Freshness and drift (multi-agent safe)

`analysis.freshness.status` compares the stored run manifest to the live worktree.
**`drifted`** means the tree changed after that run — common when another agent,
an IDE edit, or parallel WIP touched files outside your intent.

**Do not** re-analyze in a loop every time you see drift. In a shared worktree that
races other agents and burns cycles without making your edit safer.

**Instead:**

- Treat drift as a **coordination signal**, not an automatic stop.
- For conclusions that matter (imports, callers, blast radius, contract boundaries),
  **verify against the source files** in your declared scope.
- Continue editing when `edit_allowed` is true and you stay inside intent boundaries.
- **Re-analyze once** at verification boundaries: after your edits, before
  `finish_controlled_change` when the profile requires `after_run_id`, or when you
  deliberately open a new cycle.

Drift does not make run-bound context authoritative; it also does not force you to
chase freshness mid-edit. Source code is the tie-breaker while the worktree is shared.

## Capability gates

Read response status fields before claiming completeness:

| Signal | Meaning |
|--------|---------|
| `analysis.call_graph_status` | `complete` or `partial` — use `call_context`; if `partial`, read `uncertainties` |
| `call_context` edges with `target_qualname: null` | Unresolved observations — not facts |
| `mode="contract"` + `contracts` block | Truth-map when emitted; path-caller facets may be `not_available` without a typed or memory-backed anchor |
| `dataflow` | Unavailable in context contract v1 — do not infer absence of readers/writers |
| `*_summary.truncated` / `omitted` | Collection is bounded — do not claim full coverage |
| `not_available` on any facet | Unsupported or gated capability — not an empty result |

## Safety semantics (do not collapse)

| Field                  | Meaning                                                           |
|------------------------|-------------------------------------------------------------------|
| `do_not_touch`         | **Hard boundary** — separate approval or scope expansion required |
| `review_context`       | **Advisory** — review before editing; not a ban                   |
| `clone_cohort_members` | Comparison context — not automatic edit targets                   |

## Digests

- `context_artifact_digest` — binds the off-report artifact to the run.
- `context_projection_digest` — binds this request's bounded response.

Cite digests when recording review evidence; they do not authorize edits.

## Rules

- Use MCP tools only when invoked through the CodeClone plugin.
- Pass absolute `root`; MCP rejects relative roots.
- CodeClone is the source of truth — do not reinterpret findings.
- Do not fall back to CLI or local report files.
- Do not treat unresolved call edges as resolved facts.
- Do not treat `not_available` facets as "no callers exist" or "no dataflow".
- Do not treat truncated collections as complete without reading `*_summary`.
- Do not use context output to expand declared scope or override `do_not_touch`.
- Do not chase re-analysis on every `freshness.status=drifted` while another agent
  may be editing the same worktree.

## Non-goals

- Declare intent or finish verification — use `codeclone-change-control`.
- Replace `get_relevant_memory` in the mandatory edit pipeline.
- Replace `get_blast_radius` when blast-only fields suffice.
- Auto-fix or edit files based on context results.
- Force a freshness race in multi-agent worktrees.
