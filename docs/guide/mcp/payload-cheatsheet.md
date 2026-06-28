<!-- doc-scope: MCP payload cheat sheet. class: guide max-lines: 40 -->

# Payload cheat sheet

!!! warning "Non-normative"
    Normative conventions: [MCP payload conventions](../../book/25-mcp-interface/payload-conventions.md).

## Payload conventions

**IDs** — Run IDs are 8-char handles; pass the full digest when a prefix is
ambiguous. Finding lists expose `short_id`, `canonical_id`, and `html_anchor`.
`get_finding` returns `status="not_found"` for unknown ids; resources still
raise.

**Lists** — `list_findings` and
`get_report_section(section="metrics_detail")` paginate with `offset`/`limit`.
`list_hotspots` uses `limit`/`max_results` only; empty results include a closed
`empty_reason`.

**Scope filters** — `list_findings`, `list_hotspots`, and `generate_pr_summary`
accept `changed_paths` or `git_diff_ref`.

**Memory** — scoped `get_relevant_memory` defaults compact and omits routine
`run:*` trajectories. Use `query_engineering_memory` drill-down modes for full
records, trajectories, and Experiences.

**Context governance** — `partial_enforce` means response-budget packing was
applied and omitted evidence has exact drill-down under
`context_governance.omitted` / `_continuation`. `observe` means measurement
only. Default budgets are 2200 deterministic context units, or 2600 for
`get_implementation_context`.

**Artifact lookups** — `get_blast_artifact`, `get_review_receipt`, and
`get_patch_trail` return fail-closed statuses (`ok`, `not_found`, `ambiguous`,
`digest_mismatch`, …) and never recreate missing evidence from current state.

…

[Full reference →](../../book/25-mcp-interface/payload-conventions.md)
