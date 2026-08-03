---
title: "Full-McCabe complexity"
audience: public
doc_type: concept
status: draft
source_commit: "c302179335b082f30d58f29e4a238165c28e04bc"
---

## What it is

Cyclomatic complexity is computed as full McCabe over the whole normalized
control-flow graph:

```text
V(G) = E - N + 2P
```

`E` is edges, `N` is blocks, `P` is weakly connected components. The result is
floored at 1.

## Why `P` is generalized

Most tools assume one connected component. The normalized CFG keeps unreachable
code as real blocks, and unreachable code forms its own component — so the
generalized formula is what stops such a function being scored as though that
code were not there.

## Every edge counts

Exception dispatch, `finally` routing and context-manager suppression are real
control flow, and they are counted. Filtering by edge kind to reproduce older
numbers would reintroduce the second truth the normalized CFG removed.

**Expect higher values than tools that ignore exception and dead paths.** The
numbers moved corpus-wide, and the new ones are the true ones. A function whose
complexity rose between releases did not get worse; it got measured honestly.

Every defined function carries a complexity fact — clone-lane size floors no
longer gate which functions are measured.

## Risk bands

| Band | Range |
|------|-------|
| Low | ≤ 10 |
| Medium | 11–20 |
| High | > 20 |

The bands were reviewed and kept across the change. `--fail-complexity` without
a value uses 20.

## Related pages

- [Health explainability](health-explainability.md) — how complexity spends its 20 points
- [Unreachable statements](unreachable-statements.md) — the same graph, read for reachability
