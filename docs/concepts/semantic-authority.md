---
title: "Semantic authority governance"
audience: public
doc_type: concept
status: draft
source_commit: "47b7ef37dbe958c40753b933af18beb9480a8b80"
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

The report renders a paste-ready registry entry for each candidate, with the
contract id left as a placeholder — only a human can name the contract a
producer is meant to own. Promotion is a copy-paste into `pyproject.toml`.
CodeClone never writes your configuration.

Discovery proposes on the scale of a whole tree, so the panel shows the
strongest candidates and states how many it is not showing, along with the total
number of semantic sinks examined.

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
