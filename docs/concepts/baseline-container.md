---
title: "Baseline container and lane trust"
audience: public
doc_type: concept
status: draft
source_commit: "47b7ef37dbe958c40753b933af18beb9480a8b80"
---

## What it is

The baseline is one container, schema version `3.0`, holding every observation
lane a run produces. Clone findings and metrics are lanes inside it, not
separate files. One `--baseline` / `--update-baseline` pair governs the whole
container.

## Lanes

Ten lanes are defined:

`adoption_counts`, `api_surface`, `clones.blocks`, `clones.functions`,
`coupling_cohesion_observations`, `dead_code`, `dependencies`,
`module_identity`, `risk_observations`, `semantic_authority`.

Three are required: `clones.blocks`, `clones.functions`, `module_identity`.

## Per-lane trust

Trust is decided per lane, not per file. A lane is `trusted` or `unavailable`,
and an unavailable lane carries the reason it lost trust. The vocabulary is
closed — `compatible` plus these eleven, and nothing else:

`algorithm_revision`, `baseline_scope_id`, `canonicalization_version`,
`descriptor_version`, `lane_digest_mismatch`, `payload_schema`,
`payload_schema_outdated`, `python_tag`, `required_contract`,
`root_digest_mismatch`, `runtime_lane_unknown`.

This is finer than failing the artifact: a stale design-metric lane names itself
instead of condemning the lanes that are still comparable.

## Tri-state novelty

A clone group reports one of three novelty values:

| Value | Meaning |
|-------|---------|
| `known` | Present in the trusted baseline lane |
| `new` | Absent from a trusted baseline lane |
| `unavailable` | The lane could not be compared |

An unavailable lane produces `unavailable`, never `new`. A missing comparison is
not evidence of novelty, and the report says so rather than inventing a verdict.

`known` is baseline-relative. It does not mean a patch left the finding
untouched, so it cannot stand in for patch-local regression evidence.

## `baseline_scope_id`

Baseline update and baseline-relative gating both require a stable canonical
UUID under `[tool.codeclone]`:

```toml
[tool.codeclone]
baseline_scope_id = "0189f1a2-3b4c-7d8e-9f01-234567890abc"
```

Without it CodeClone exits 2 with `baseline_scope_id is required for baseline
update and gating`. The scope id is what stops one project's baseline being
compared against another's; publishing refuses a container whose scope id does
not match the configured one.

## Related pages

- [Reports and baselines](reports.md) — how a run's findings are stored
- [Upgrading from 2.1.0a1 to 2.1.0a2](../guides/migration-a1-a2.md) — regenerating an older baseline
- [Configuration reference](../reference/configuration.md) — the keys involved
