---
name: codeclone-implementation-context
description: Before broad rg/grep, non-trivial planning, unclear scope, contract/schema work, or resuming another agent — call get_implementation_context once to bound the implementation frontier. Then use targeted source reads. Read-only; never grants edit permission.
---

# CodeClone Implementation Context

Bounded orientation from one stored `analyze_repository` run. Not edit permission.

## Mandatory triggers

Call once before:

- repo-wide or recursive `rg`, `grep`, `find`, or custom search scripts;
- cross-module planning, contract/schema/version work, or hub edits;
- resuming another agent/session;
- declaring a non-obvious edit scope.

Skip only for obvious local work with a complete known file boundary.

Do not search broadly first and call this afterward merely to satisfy the workflow.

## Pattern

`get_implementation_context` → targeted reads / narrow `rg` → `codeclone-change-control`

Do not loop this tool to avoid reading source.

## Subject

Choose one subject strategy:

| Input                      | Use for                                                                                                               |
|----------------------------|-----------------------------------------------------------------------------------------------------------------------|
| `query="name"`             | Structural name search: definitions, call targets, imports in the stored run. Not file-text or regex. `mode` ignored. |
| `paths=[...]`              | Known files or modules                                                                                                |
| `symbols=["pkg.mod:func"]` | Exact qualnames (`:` not `.`)                                                                                         |
| `intent_id=...`            | Alone: active intent `allowed_files`. With explicit `paths`/`symbols`: keeps that subject and adds `change_control`.  |
| `changed_scope=true`       | Live git-dirty paths (not intent scope as subject)                                                                    |

`paths` and `symbols` may be combined when both are known.

Rules:

- whole-repository context is never inferred;
- never mix `changed_scope` with `paths` or `symbols`;
- never mix `query` with any other subject input;
- never guess unresolved symbols;
- weaker `match_tier` hits require source verification.

## Mode

For paths, symbols, intent scope, or changed scope (not `query`):

- `implementation` — sites, nearby relations, likely tests;
- `impact` — callers, dependents, baseline-sensitive findings;
- `contract` — schemas, version constants, persistence and public surfaces.

## Examples

```text
get_implementation_context(root=<abs>, query="as_sequence")

get_implementation_context(
    root=<abs>,
    paths=["codeclone/contracts/__init__.py"],
    mode="impact",
)

get_implementation_context(
    root=<abs>,
    paths=["pkg/mod.py"],
    intent_id="<id>",
    mode="implementation",
)
```

Use `rg`/`grep` afterward for text patterns, comments, and non-symbol strings.

Engineering Memory keyword search → `codeclone-engineering-memory`.

## Read results

- `needs_analysis` → analyze once, retry.
- `no_matches` (query) → refine query; do not jump to repo-wide search.
- `subject_not_found` / `no_current_work` → fix subject; do not widen to repo root.
- `freshness.status:"drifted"` → verify live source; no re-analyze loop.
- truncated/omitted summaries, unresolved call edges → incomplete evidence, not absence.
- For compact/normal detail, `context_governance.mode="partial_enforce"` means
  large facet lanes may be omitted with exact drill-down in
  `context_governance.omitted`; mandatory subject/freshness facts remain inline.
- When `analysis.context_page_retrieval` is present, use
  `get_implementation_context_page(root=<abs>, context_projection_digest=analysis.context_projection_digest, facet=...)`
  for exact facet continuation. This is session-local to MCP run history and
  returns `not_found` rather than recomputing fresh context. Facet pages
  themselves are `mode="observe"` retrieval responses.

## Hard limits

- MCP tools only. Do not fall back to CLI or local report files.
- Never authorizes edits (`start_controlled_change` + `edit_allowed:true` only).
- Do not widen scope, touch `do_not_touch`, or edit `review_context`/clone cohorts from this output.
- Memory lane here ≠ `get_relevant_memory`.

Done when you can name: implementation files, review/dependent files, contracts, uncertainties, proposed
`allowed_files`, and what to read next.
