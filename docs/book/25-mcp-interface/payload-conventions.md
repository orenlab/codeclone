<!-- doc-scope: MCP payload conventions. class: contract max-lines: 150 -->

# MCP payload conventions

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

**Budget nulls** — `check_patch_contract` uses `null` for disabled numeric
thresholds. Boolean policy gates use `forbid_*` names.

**Long context** — `do_not_touch`, `review_context`, and similar sections
include `total`, `shown`, and `truncated` summaries.

## Response governance compatibility audit

Response context governance rolls out additively. Until capability metadata
advertises a leaner shape, clients must treat the current payload shape as the
compatibility contract.

Current `finish_controlled_change` compatibility facts:

| Field                                                    | Current role                                              | Compatibility decision                                                                |
|----------------------------------------------------------|-----------------------------------------------------------|---------------------------------------------------------------------------------------|
| `summary.receipt`                                        | compact created / skipped / failed status                 | keep; dashboards and skills use it as the receipt status signal                       |
| `receipt.receipt_version` / `verdict` / `receipt_digest` | top-level receipt identity and compact routing fields     | prefer for identity checks before drill-down                                          |
| `receipt.content`                                        | complete human-readable markdown receipt                  | keep inline while finish remains observe-only                                         |
| `receipt.receipt_retrieval`                              | route to the durable structured receipt                   | use `get_review_receipt(..., format="structured")` for machine-readable receipt facts |
| `receipt.receipt`                                        | legacy duplicate typed alias nested under markdown output | omitted by default; do not depend on it in finish responses                           |
| `receipt_error`                                          | receipt failure reason                                    | keep; failed receipt creation prevents `auto_clear`                                   |

Client and integration audit:

| Surface               | Current dependency                                                          | Response-governance requirement                                   |
|-----------------------|-----------------------------------------------------------------------------|-------------------------------------------------------------------|
| MCP tests / snapshots | assert `summary.receipt`, receipt identity, and durable receipt retrieval   | update first when finish packing semantics change                 |
| VS Code extension     | discovers tools through `tools/list`; does not own a separate finish schema | tolerate current shape and future capability metadata             |
| Claude Desktop bundle | launches `codeclone-mcp`; no independent payload parser                     | no bundle shape change before MCP capability metadata             |
| Claude Code plugin    | skills describe the workflow, not a custom parser                           | sync skills when finish response governance is enforced           |
| Codex plugin          | skills describe the workflow, not a custom parser                           | sync skills when finish response governance is enforced           |
| Cursor plugin         | skills/rules describe the workflow and receipt requirement                  | sync skills and rules when finish response governance is enforced |

Before any default payload removal, MCP must advertise pre-call capability
metadata for the response-governance contract. Clients should be able to detect:

- context-governance contract version;
- passive `observe` mode vs enforced response budgets;
- whether `finish_controlled_change` still includes the typed receipt alias;
- whether durable receipt, Patch Trail, blast-radius, implementation-context
  page, and omitted-evidence drill-down resources are available.

Payload slimming without that metadata is a contract break, even during alpha.

### Response `context_governance`

Selected workflow and evidence tools include a `context_governance` envelope.
It estimates the returned response and declares whether the tool only measured
the payload or actually applied response-budget packing:

| Field                              | Meaning                                                                                                    |
|------------------------------------|------------------------------------------------------------------------------------------------------------|
| `contract_version`                 | response-governance contract version                                                                       |
| `estimator`                        | deterministic estimator, currently `utf8_bytes_div_4_v1`                                                   |
| `estimated`                        | estimated context units for the serialized response with `estimated` normalized to `0` during measurement  |
| `limit`                            | active default response target                                                                             |
| `mode`                             | `observe` for measurement-only responses; `partial_enforce` when recoverable lanes may be compacted        |
| `enforcement.response_budget`      | whether the response is packed against the declared context-unit budget                                    |
| `enforcement.nested_budget`        | whether nested evidence calls receive a propagated remaining budget                                        |
| `enforcement.omission`             | whether omitted lanes are disclosed through `context_governance.omitted`                                   |
| `enforcement_blocked`              | missing exact retrieval capabilities that prevent safe response-budget enforcement                         |
| `capabilities.typed_receipt_alias` | whether the legacy typed receipt alias contract is still recognized; default finish uses retrieval instead |
| `drill_down`                       | exact object routes and blocked continuation/snapshot routes for evidence that may be omitted              |
| `response`                         | optional tool-specific response budget scope and projection digest                                         |

`mode="observe"` means the response is measured but not packed. It is expected
for drill-down retrieval tools that already return one exact object or one exact
page, such as `get_blast_artifact`, `get_review_receipt`, `get_patch_trail`,
`get_memory_projection_page`, and `get_implementation_context_page`.
`mode="partial_enforce"` means mandatory control facts stay inline while
recoverable evidence lanes may be compacted or omitted with exact drill-down.
Neither mode authorizes edits, weakens findings, or replaces tool-specific
contracts.

Platform Observability uses `context_governance.estimated` as the MCP response
context-pressure estimate when the envelope is present. Older observer storage
fields may still be named `response_tokens`; treat their values as deterministic
context units, not model-specific tokenizer counts.

For `finish_controlled_change`, `context_governance.response` describes the
whole returned finish response. It includes `tool="finish_controlled_change"`,
`budget_scope="whole_response"`,
`evidence_policy="response_budget_with_durable_artifact_lookup"`, and a
`finish_projection_v1` digest. Finish responses use `partial_enforce`: control
and safety facts remain inline, while recoverable advisory lanes such as receipt
markdown content or Patch Trail detail may be compacted. Omitted finish lanes
are disclosed under `context_governance.omitted` and point to
`get_review_receipt(root, run_id, receipt_digest, format=...)` or
`get_patch_trail(root, patch_trail_digest, format="structured")`.

For `start_controlled_change`, `context_governance.response` describes the
whole returned start response with `tool="start_controlled_change"` and a
`start_projection_v1` digest. When a durable blast artifact is stored, default
start responses carry a safety-complete blast summary and a
`blast_artifact` pointer. Full omitted blast evidence is retrieved exactly with
`get_blast_artifact(root, run_id, blast_artifact_id)`. `get_blast_radius`
remains current recomputation, not historical drill-down. If artifact storage is
unavailable, start returns full blast evidence inline. Start responses use
`partial_enforce` only when an immutable blast artifact is available; fallback,
queued, and needs-analysis responses stay in `observe`.

For `get_relevant_memory`, `context_governance.response` describes the whole
memory retrieval response with `tool="get_relevant_memory"` and a
`memory_retrieval_projection_v1` digest. The existing `records`,
`trajectories`, `experiences`, coverage, and retrieval-policy fields remain
present according to their current lane caps. When a lane has an omitted tail,
`continuation.lanes.<lane>.page` carries a digest-bound cursor for
`get_memory_projection_page`. The page route is an exact continuation only while
the normalized request, lane ordering version, and lane identity digest still
match; otherwise it fails closed with `snapshot_mismatch`. `context_governance`
uses `partial_enforce` for compact scoped retrieval and `observe` for
`detail_level="full"` and for exact continuation pages.

For `get_implementation_context`, `context_governance.response` describes the
whole implementation-context response with `tool="get_implementation_context"`
and an `implementation_context_projection_v1` digest. The existing
`budget_summary` remains an item-count budget for emitted context entries; it is
not the serialized response context budget. The response also carries
`analysis.context_page_retrieval` when exact session-local facet pages are
available. Use `get_implementation_context_page(root, context_projection_digest,
facet)` with `analysis.context_projection_digest` to retrieve a saved facet
lane. This is exact only for the MCP session run-history artifact; if the
projection is gone, the tool returns `status="not_found"` instead of
recomputing fresh context. Implementation-context responses use
`partial_enforce` for compact/normal detail and propagate nested memory budget;
`detail_level="full"` and exact facet pages stay in `observe`.

Current drill-down reachability is intentionally conservative:

- known memory records and known trajectories have exact object lookup through
  `query_engineering_memory`; known Experiences use
  `query_engineering_memory(mode="experience_get")`;
- omitted memory record, trajectory, and Experience tails have digest-bound
  continuation through `get_memory_projection_page`;
- structured receipts, Patch Trail, and blast artifacts have durable exact
  retrieval routes;
- implementation-context facet pages have exact session-local retrieval through
  `get_implementation_context_page`.

---
