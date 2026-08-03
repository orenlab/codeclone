---
title: "Unreachable statements"
audience: public
doc_type: concept
status: draft
source_commit: "c302179335b082f30d58f29e4a238165c28e04bc"
---

## What it is

The dead-code lane asks two orthogonal questions. `symbol` asks whether a
definition is referenced. `unreachable_statement` asks whether a statement
inside a live definition can run.

## The predicate

One predicate over one graph:

> A statement cannot run exactly when its block is not reachable from the CFG
> entry by directed traversal of block successors.

There is no separate clause for code after a terminator and none for a literal
guard. The normalized CFG already expresses both structurally — it emits the
post-terminator tail as a block with no incoming edge, and it suppresses the edge
into a branch whose guard is a literal constant that forbids entry. Exception
dispatch, `finally` routing and context-manager suppression are ordinary edges,
so traversal answers them too.

Policy version: `1`.

## Reasons are evidence, not verdicts

A finding names a cause a reader recognises — `after_terminator`,
`literal_condition`, or `unreachable_block`. The block was already decided
unreachable by traversal before any cause was consulted. No verdict depends on
the label.

## Honest abstention

The rule is the declared predicate and nothing more: no value inference, no
propagation. The moment a name lookup counted as evidence, this would stop being
the rule it claims to be. A statement CodeClone cannot prove unreachable is
simply not reported.

Findings are emitted per maximal region, not per statement — a long dead tail is
one finding with a statement count, not many findings.

## What they do not affect

Unreachable statements are reported and stored in the dead-code lane. They are
**not** a health input and **not** a gate input today:

- the dead-code health dimension counts symbols with no production references —
  unreferenced, or referenced only from tests;
- `--fail-dead-code` reads the high-confidence symbol count, so unreachable
  statements cannot trip it.

Measured on this repository: 11 unreachable-statement findings, 0 dead-code
symbols, dead-code health dimension **100**. Treat them as review signal, not as
something a pipeline currently fails on.

## Related pages

- [Health score](health-score.md) — what the dead-code dimension actually counts
- [Full-McCabe complexity](complexity.md) — the same normalized CFG, counted differently
