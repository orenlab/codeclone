<!-- doc-scope: MCP payload cheat sheet. class: guide max-lines: 40 -->

# Payload cheat sheet

!!! warning "Non-normative"
    Normative conventions: [MCP payload conventions](../../book/25-mcp-interface/payload-conventions.md).

## Payload conventions

Short reference for response structure patterns across the tool surface.

**IDs** — Run IDs are 8-char hex handles. Finding IDs are short prefixed
forms. Both accept the full canonical form as input.

**Detail levels** — `summary` (default for lists), `normal` (default for
single finding), `full` (compatibility payload with URIs).

**Pagination** — `list_findings` and
`get_report_section(section="metrics_detail")` support `offset` and `limit`.
`list_hotspots` supports `limit` and `max_results` only (no `offset`).

**Changed-scope filters** — `list_findings`, `list_hotspots`, and
`generate_pr_summary` accept `changed_paths` or `git_diff_ref` for PR
projection.

**Threshold context** — Empty `check_*` responses include
`threshold_context` showing whether the run is genuinely quiet or simply
below the active threshold.

**Engineering Memory** — `get_relevant_memory` omits routine `run:*` trajectories
from `trajectories[]` by default. Use `query_engineering_memory` trajectory
modes with `filters.include_routine=true` to include them. Scoped retrieval
defaults to `detail_level=compact`; use `full` or
`query_engineering_memory(mode=get)` for complete payloads.

**Context governance** — `context_governance.mode="partial_enforce"` means the
tool applied response-budget packing and any omitted evidence is listed under
`context_governance.omitted` with an exact drill-down route. `mode="observe"`
means measurement only; this is expected for exact retrieval/page tools such as
`get_blast_artifact`, `get_review_receipt`, `get_patch_trail`,
`get_memory_projection_page`, and `get_implementation_context_page`.

…

[Full reference →](../../book/25-mcp-interface/payload-conventions.md)
