---
title: "Health explainability"
audience: public
doc_type: concept
status: draft
source_commit: "47b7ef37dbe958c40753b933af18beb9480a8b80"
---

## What it is

A health score that cannot be explained cannot be acted on. Every surface that
shows a dimension also states the arithmetic behind it, and reads the dimension
weight from the same contract that computed the score — so a rendered
contribution can never drift from the number it explains.

## Dimension weights

| Dimension | Weight |
|-----------|--------|
| Clones | 0.25 |
| Complexity | 0.20 |
| Cohesion | 0.15 |
| Coupling | 0.10 |
| Dead code | 0.10 |
| Dependencies | 0.10 |
| Coverage | 0.10 |

## The clones card: density, not share

The clones dimension is a **density**: active function and block clone groups
divided by analyzed files.

It is not a share of files and not a share of callables. One group can span
files, one file can hold several groups, and one callable can participate in
several groups — so a percentage of files would be a different number answering
a different question. Duplication is reported as a density and as *deduplicated
participants*.

The curve is piecewise: mild at low density, steep in the structural-debt zone,
floored when duplication is systemic.

| Density | Score |
|---------|-------|
| 0 | 100 |
| 5% | 90 |
| 20% | 50 |
| ≥ 50% | 0 |

A long list of clone cards therefore says nothing about the score on its own,
which is why every surface showing the cards also states the arithmetic.

## Bounded dimensions

Complexity and coupling each spend their 100 points across four bounded terms —
typical (30), elevated tail (30), extreme tail (30), single worst outlier (10).

Bounding is the point. An unbounded formula lets one pathological class or
function spend the whole dimension, pinning it at 0 where it can no longer move
when the code improves. Two of the four terms are shares rather than counts, so
a dimension does not punish a project for being large.

The reference shares are measured from a real corpus, not chosen.

## Gate equals measure

`--fail-health` compares the *same* score the report displays against your
threshold. There is no second, stricter number computed for gating purposes.

If the report says 72 and your threshold is 75, the gate fails at 72 — and the
dimension breakdown you are reading is the breakdown the gate acted on.

## Related pages

- [Health score](health-score.md) — what the score is and is not
- [Full-McCabe complexity](complexity.md) — why complexity values rose
- [CI integration](../guides/ci-integration.md) — gating on health
