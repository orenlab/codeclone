---
title: "Near-miss clones"
audience: public
doc_type: concept
status: draft
source_commit: "c302179335b082f30d58f29e4a238165c28e04bc"
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

## Token domains

The tier confirms distance in two declared token spaces, and every reported
pair names the one that certified it (`token_domain` in the report payload):

- **`y8`** — the normalized statement tokens the tier has always used. Local
  names normalize; attribute names stay literal.
- **`renamed`** — the same statements re-tokenized through the
  [renamed-structure](renamed-structure-clones.md) ordinal canonicalization, so
  a pair whose only differences are a consistent renaming (locals and receiver
  attributes) plus one true edit is found within the same `K = 1` budget. Under
  y8 tokens the attribute renames alone would price the pair out.

The budget, the confirmation algorithm and the deterministic witness law are
identical in both domains; the token spaces are never mixed. A pair confirmable
in both domains is reported exactly once, in the `y8` domain, so everything the
tier reported before the renamed domain existed is unchanged. Distance 0 in the
renamed domain is the renamed-structure tier's business and never appears here.
Witness lines always point at the real source statements — canonical spellings
exist only for comparison.

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
