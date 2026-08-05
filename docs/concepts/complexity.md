---
title: "Complexity: two metrics, one owner each"
audience: public
doc_type: concept
status: draft
source_commit: "c302179335b082f30d58f29e4a238165c28e04bc"
---

## Two explicitly distinct metrics

CodeClone reports complexity as two deliberately separate numbers:

| Metric | What it counts | Role |
|--------|----------------|------|
| `cyclomatic_complexity` | Authored decisions in the source, over AST constructs | **Public.** Used by health, risk bands and policy gates |
| `cfg_cyclomatic_complexity` | Full McCabe `V(G) = E − N + 2P` over the complete normalized CFG | **Diagnostic.** Reported alongside; never a health or gate input |

Neither is derived from the other, and they are allowed to disagree — that
disagreement is information. A `try/finally` adds routing edges the CFG metric
counts, while the source metric holds still because no new decision was
authored. A ternary inside an assignment is an authored decision the source
metric counts, while the statement-level CFG may not branch on it.

## The public metric: authored decisions

`cyclomatic_complexity` is a deterministic source-level decision count: the
base callable is one independent path, and each construct contributes per the
fixed table below. It is entirely independent of CFG normalization and
reachability — `python -O`, unreachable code, and exception routing never move
it.

| Construct | Contribution |
|-----------|--------------|
| Base callable | 1 |
| `if` / each `elif` | +1 |
| Ternary (`x if c else y`) | +1 |
| `while` | +1 |
| `for` / `async for` | +1 |
| Each comprehension generator (`for`) | +1 |
| Each `if` filter in a comprehension | +1 |
| `and` / `or` chain | +1 per short-circuit boundary, in any expression position (`return cached or load()` counts) |
| Each `except` / `except*` clause | +1 |
| Each `match` case | +1 — except the last unguarded `case _` |
| Guard on any `case` | +1 (so `case _ if allowed:` is not a default) |
| `case A \| B` | +1 per additional alternative |
| `assert` | +1 |
| `with` / suppressing context managers | 0 |
| `try`-`else`, `finally`, loop-`else` | 0 (derived routes) |
| `return` / `raise` / `break` / `continue` | 0 (jumps, no own check) |
| `yield` / `await` / walrus | 0 |
| Implicit exception edges | 0 (not authored) |

Nested `def` / `class` bodies do not count toward the outer function — they
are (or belong to) their own metric units. A lambda is not a metric unit, so
its authored decisions count toward the function whose source contains it.

Every defined function carries a complexity fact — clone-lane size floors do
not gate which functions are measured.

## The diagnostic: full McCabe over the CFG

`cfg_cyclomatic_complexity` is computed over the whole normalized control-flow
graph:

```text
V(G) = E - N + 2P
```

`E` is edges, `N` is blocks, `P` is weakly connected components, floored at 1.
The graph is never filtered: exception dispatch, `finally` routing and
context-manager suppression are real control flow and are counted, and
unreachable code forms its own component (which is why `P` is generalized).
Expect it to read higher than the public metric on exception-heavy code — that
gap is the point: it shows how much runtime routing surrounds the decisions
you actually wrote.

## Risk bands

Risk bands apply to the public `cyclomatic_complexity` only:

| Band | Range |
|------|-------|
| Low | ≤ 10 |
| Medium | 11–20 |
| High | > 20 |

`--fail-complexity` without a value uses 20.

## Comparability across versions

The public metric's algorithm identity is `COMPLEXITY_ALGORITHM_REVISION`.
Metrics baselines record it per lane: stored complexity observations from an
older revision are reported as untrusted for that lane rather than silently
diffed against current values.

## Related pages

- [Health explainability](health-explainability.md) — how complexity spends its 20 points
- [Unreachable statements](unreachable-statements.md) — the CFG, read for reachability
