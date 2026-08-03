---
title: "Semantic authority governance"
audience: public
doc_type: concept
status: draft
source_commit: "c302179335b082f30d58f29e4a238165c28e04bc"
---

## What it is

Semantic authority answers one governance question: for a given contract, which
function is allowed to produce the fact, and which functions may only adapt it.
A contract is governed once a human writes it into `pyproject.toml`. Until then
CodeClone can describe what it found, but it governs nothing.

## The registry

`[[tool.codeclone.authority]]` is an array of tables. Every entry declares all
five fields; a missing or unknown key is a contract error.

```toml
[[tool.codeclone.authority]]
contract_id = "report.envelope/v1"
canonical_owner = "codeclone.report.document.builder:build_report"
allowed_adapters = ["codeclone.report.renderers.markdown:render"]
forbidden_raw_inputs = []
required_provenance = ["codeclone.report.document.builder:build_report"]
```

| Field | Rule |
|-------|------|
| `contract_id` | `<name>/v<positive-int>`, unique across entries |
| `canonical_owner` | `module:symbol`, unique across entries |
| `allowed_adapters` | `module:symbol` list; must not repeat `canonical_owner` |
| `forbidden_raw_inputs` | string list |
| `required_provenance` | string list, must not be empty |

Every list is sorted and duplicate-free, and entries are sorted by
`contract_id`. Registry contract version is `1`.

## Statuses

A governed sink reports one status:

`authoritative`, `adapter`, `shadow`, `mixed`, `unavailable`.

`unavailable` is an abstention, and it never travels bare: the sink carries the
reasons it could not be resolved, copied from the contract IR failure states. An
abstention without a reason is not a fact, so the report renders the reason
beside the status.

## Discovery: tools propose, humans own

`--semantic-authority` collects report-only candidates and provenance facts. It
is off by default and it writes nothing.

Candidates are ranked by evidence strength:

| Level | Evidence |
|-------|----------|
| `exact_contract_ir` | Identical contract IR |
| `same_effect_signature` | Same effect signature |
| `same_output_fact_and_input_family` | Same output fact, same input family |
| `overlapping_transform_chain` | Shared transform chain |
| `divergent_projection` | Shared fact, divergent projection |

Each rendered row carries a paste-ready registry entry, with the contract id left
as a placeholder — only a human can name the contract a producer is meant to own.
Promotion is a copy-paste into `pyproject.toml`. CodeClone never writes your
configuration.

Discovery proposes on the scale of a whole tree, so the HTML table is cut twice:
it carries only the three strongest levels (`exact_contract_ir`,
`same_effect_signature`, `same_output_fact_and_input_family`), and at most 50
rows of those. The caption states the cut where it happens — how many of how many
are shown, a per-level histogram of all candidates with the below-cut levels
named, and the total raw sinks discovery examined.

## Reading the tail over MCP

The rows the HTML table cut are served as bounded pages:

```text
check_authority(section="candidates", cursor=..., page_size=...)
```

`section` defaults to `violations`, unchanged. `section="candidates"` is the only
way to reach the discovery tail — candidates are served *only* as bounded pages.
Page size defaults to 20 and is capped at 50.

Pagination fails closed. Each cursor is digest-bound to the run and the
population it was cut from, so a cursor from another projection, another
ordering, or a changed run is refused rather than silently resumed against
different data.

## Gating

`--fail-on-authority-violation` exits 3 when a governed contract has a violation.
It requires a reviewed registry entry: with no entry there is no owner, and with
no owner there is nothing to violate.

Violation kinds: `multiple_independent_producers`, `shadow_projection`,
`owner_bypass`, `reconstructed_contract`, `divergent_failure_semantics`,
`divergent_canonicalization`.

## Related pages

- [Configuration reference](../reference/configuration.md) — where the registry lives
- [Baseline container and lane trust](baseline-container.md) — the `semantic_authority` lane
