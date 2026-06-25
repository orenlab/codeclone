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

| Field                                                         | Current role                                              | Compatibility decision                                                                 |
|---------------------------------------------------------------|-----------------------------------------------------------|----------------------------------------------------------------------------------------|
| `summary.receipt`                                             | compact created / skipped / failed status                 | keep; dashboards and skills use it as the receipt status signal                        |
| `receipt.receipt_version` / `verdict` / `receipt_digest`      | top-level receipt identity and compact routing fields     | prefer for identity checks before reading the full typed alias                         |
| `receipt.content`                                             | complete human-readable markdown receipt                  | keep until durable typed receipt drill-down exists                                     |
| `receipt.receipt`                                             | complete typed receipt alias nested under markdown output | keep as the machine-readable compatibility path until another typed path is advertised |
| `receipt_error`                                               | receipt failure reason                                    | keep; failed receipt creation prevents `auto_clear`                                    |

Client and integration audit:

| Surface               | Current dependency                                                          | Response-governance requirement                                   |
|-----------------------|-----------------------------------------------------------------------------|-------------------------------------------------------------------|
| MCP tests / snapshots | assert `summary.receipt` and nested typed receipt fields                    | update first when the compatibility alias moves                   |
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
- whether durable receipt, Patch Trail, blast-radius, and omitted-evidence
  drill-down resources are available.

Payload slimming without that metadata is a contract break, even during alpha.

### Passive `context_governance`

Selected workflow and evidence tools now include a passive
`context_governance` envelope. It estimates the returned response but does
**not** omit evidence yet:

| Field                              | Meaning                                                                                                   |
|------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `contract_version`                 | response-governance contract version                                                                      |
| `estimator`                        | deterministic estimator, currently `utf8_bytes_div_4_v1`                                                  |
| `estimated`                        | estimated context units for the serialized response with `estimated` normalized to `0` during measurement |
| `limit`                            | active default response target, currently advisory                                                        |
| `mode`                             | `observe` until evidence omission is enforced                                                             |
| `enforcement.response_budget`      | `false` while no response evidence is omitted                                                             |
| `enforcement_blocked`              | missing exact retrieval capabilities that prevent safe response-budget enforcement                         |
| `capabilities.typed_receipt_alias` | `true` while `receipt.receipt` remains the typed compatibility path                                       |
| `drill_down`                       | exact object routes and blocked continuation/snapshot routes for evidence that may later be omitted        |
| `response`                         | optional tool-specific response budget scope and projection digest                                        |

Treat `mode="observe"` as telemetry and compatibility metadata, not as proof
that the response is already bounded. It also does not authorize edits, weaken
findings, or replace tool-specific contracts.

Platform Observability uses `context_governance.estimated` as the MCP response
context-pressure estimate when the envelope is present. Older observer storage
fields may still be named `response_tokens`; treat their values as deterministic
context units, not model-specific tokenizer counts.

For `finish_controlled_change`, `context_governance.response` describes the
whole returned finish response. It includes `tool="finish_controlled_change"`,
`budget_scope="whole_response"`, `evidence_policy="observe_only_no_omission"`,
and a `finish_projection_v1` digest. The response is measured as one payload,
but no evidence is removed while receipt, Patch Trail, blast artifact, or
omitted-tail drill-down remains blocked.

For `start_controlled_change`, `context_governance.response` describes the
whole returned start response with `tool="start_controlled_change"` and a
`start_projection_v1` digest. When a durable blast artifact is stored, default
start responses carry a safety-complete blast summary and a
`blast_artifact` pointer. Full omitted blast evidence is retrieved exactly with
`get_blast_artifact(root, run_id, blast_artifact_id)`. `get_blast_radius`
remains current recomputation, not historical drill-down. If artifact storage is
unavailable, start returns full blast evidence inline.

For `get_relevant_memory`, `context_governance.response` describes the whole
memory retrieval response with `tool="get_relevant_memory"` and a
`memory_retrieval_projection_v1` digest. The existing `records`,
`trajectories`, `experiences`, coverage, and retrieval-policy fields remain
present according to their current lane caps. When a lane has an omitted tail,
`continuation.lanes.<lane>.page` carries a digest-bound cursor for
`get_memory_projection_page`. The page route is an exact continuation only while
the normalized request, lane ordering version, and lane identity digest still
match; otherwise it fails closed with `snapshot_mismatch`. `context_governance`
is still measurement only until response-budget enforcement is explicitly
enabled.

For `get_implementation_context`, `context_governance.response` describes the
whole implementation-context response with `tool="get_implementation_context"`
and an `implementation_context_projection_v1` digest. The existing
`budget_summary` remains an item-count budget for emitted context entries; it is
not the serialized response context budget.

Current drill-down reachability is intentionally conservative:

- known memory records and known trajectories have exact object lookup through
  `query_engineering_memory`; known Experiences use
  `query_engineering_memory(mode="experience_get")`;
- omitted memory record, trajectory, and Experience tails have digest-bound
  continuation through `get_memory_projection_page`;
- structured receipts, Patch Trail, and blast artifacts have durable exact
  retrieval routes;
- implementation-context facet pages remain blocked until exact artifact pages
  are introduced.

---
