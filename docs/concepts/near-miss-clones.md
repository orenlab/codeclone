---
title: "Near-miss clones"
audience: public
doc_type: concept
status: draft
source_commit: "47b7ef37dbe958c40753b933af18beb9480a8b80"
---

## What it is

Exact fingerprints cannot match two functions whose normalized statement
sequences differ at all, so a copy carrying one extra statement is invisible to
every other clone tier. The near-miss tier closes that gap.

Two clone-eligible units are a near-miss pair when their normalized statement
sequences differ by at least one and at most **one** inserted, deleted or
replaced statement.

## The rule

`K = 1`. An integer distance with a named bound — no similarity score, no
tunable floor:

- distance 0 is the exact tier's business and never enters near-miss;
- a divergence landing on a control-flow anchor rather than a statement is not a
  statement edit, so it does not qualify.

## Opt-in and confinement

The channel is produced only with `--near-miss` (or `near_miss = true` in
`pyproject.toml`), off by default.

It is gate-neutral by construction rather than by a flag someone could flip:
near-miss pairs never enter the clone groups, so they reach no observation lane,
no baseline novelty and no gate. Turning the flag on cannot change an exit code.

```bash
codeclone --near-miss
```

## Related pages

- [Structural analysis](structural-analysis.md) — the clone tiers that do gate
- [Baseline container and lane trust](baseline-container.md) — the lanes near-miss stays out of
