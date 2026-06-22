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

## Phase 34A compatibility audit

Phase 34A introduces response context governance in small slices. Until the
capability marker exists, clients must assume the current payload shape is the
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

| Surface               | Current dependency                                                          | Phase 34A requirement                                             |
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

`finish_controlled_change` now includes a passive `context_governance` envelope.
It estimates the returned response but does **not** omit evidence yet:

| Field                              | Meaning                                                                                                   |
|------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `contract_version`                 | response-governance contract version                                                                      |
| `estimator`                        | deterministic estimator, currently `utf8_bytes_div_4_v1`                                                  |
| `estimated`                        | estimated context units for the serialized response with `estimated` normalized to `0` during measurement |
| `limit`                            | active default response target, currently advisory                                                        |
| `mode`                             | `observe` until evidence omission is enforced                                                             |
| `enforcement.response_budget`      | `false` while no response evidence is omitted                                                             |
| `capabilities.typed_receipt_alias` | `true` while `receipt.receipt` remains the typed compatibility path                                       |

Treat `mode="observe"` as telemetry and compatibility metadata, not as proof
that the response is already bounded.

---
