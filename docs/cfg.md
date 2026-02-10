# Control Flow Graph (CFG) — Design and Semantics

This document describes the **Control Flow Graph (CFG)** model used by **CodeClone**,
its design goals, semantics, and known limitations.

CFG in CodeClone is **not** intended to be a full or precise execution model of Python.
Instead, it is a **structural abstraction** optimized for **stable and low-noise clone detection**.

---

## Design Goals

The CFG implementation in CodeClone (CFG v1) is designed to:

- capture **structural control-flow shape** of functions,
- be **deterministic and reproducible**,
- remain **robust to small refactorings**,
- maximize **signal-to-noise ratio** for clone detection,
- scale well to large Python codebases.

The primary consumer of CFGs in CodeClone is **structural fingerprinting**, not program analysis.

---

## Scope

CFGs are built:

- **per function / method**,
- using Python AST (`ast.FunctionDef`, `ast.AsyncFunctionDef`),
- without interprocedural analysis.

Each function produces an independent CFG.

---

## CFG Structure

### Blocks

A CFG consists of **basic blocks**.

Each block contains:

- a unique, deterministic `id`,
- a list of normalized AST statements (`ast.stmt`),
- a set of successor blocks,
- a termination flag (`is_terminated`).

Blocks are ordered and numbered deterministically to ensure stable fingerprints.

---

### Edges

Edges represent **structural control flow**:

- sequential execution,
- conditional branching (`if`),
- looping constructs (`for`, `while`).

Edges do **not** represent runtime conditions or probabilities.

---

## Supported Control Structures

### Sequential statements

Sequential statements are appended to the current block until a control split occurs.

---

### `if / else`

An `if` statement creates:

- a condition block,
- a `then` block,
- an optional `else` block,
- a merge (after) block.

Both branches always reconverge at an explicit after-block.

If the condition is a short‑circuit boolean (`and`/`or`), it is expanded into a
**micro‑CFG** with one block per operand and explicit branch edges between them.

---

### `while` loops

A `while` loop produces:

- a loop condition block,
- a body block,
- an optional `else` block,
- an after-loop block.

The condition block always has two successors:

- loop body,
- else/after-loop path.

---

### `for` loops

A `for` loop is modeled similarly to `while`:

- an iteration-expression block,
- a body block,
- an optional `else` block,
- an after-loop block.

The iterable expression (`range(...)`, etc.) is represented as a statement
inside the condition block.

---

## `break` and `continue` Semantics (CFG v1)

In CFG v1:

- `break` and `continue` are explicit terminating statements,
- each maps to a deterministic jump target through loop context:
  - `break` -> loop after-block,
  - `continue` -> loop condition/iteration block,
- `for/while ... else` remains reachable only on normal loop completion
  (not through `break` paths).

This preserves structural loop semantics while keeping deterministic graph shape.

---

## Ordered Branch Semantics

To avoid false equivalence from branch reordering, CFG v1 preserves:

- `match case` evaluation order via indexed case-test blocks,
- `except` handler order via indexed handler-test blocks.

---

## What CFG v1 Does NOT Model

### No interprocedural flow

- Function calls are treated as atomic expressions.
- No inlining or call graph construction.

---

### No data-flow analysis

- No variable liveness tracking.
- No value propagation.
- No alias analysis.

---

### Limited exception flow

- `try / except / finally` blocks are represented structurally.
- `try/except` edges are created **only** from statements that may raise:
  function calls, attribute access, indexing, `await`, `yield from`, and `raise`.
- No interprocedural exception propagation is modeled.

This keeps CFGs deterministic while reducing false differences between safe and
potentially‑raising code.

---

## Determinism Guarantees

CFG v1 guarantees:

- deterministic block numbering,
- stable successor ordering,
- reproducible CFG fingerprints across runs.

This is critical for CI usage and baseline comparison.

## Python Tag Consistency for Baseline Checks

Due to AST differences between interpreter versions, baseline compatibility is pinned to
the same `python_tag` (for example `cp313`), not full patch version equality.

This keeps clone detection deterministic while allowing patch updates within the same tag.

CI gating uses the baseline tag policy, while the test matrix validates runtime
compatibility across Python 3.10-3.14.

---

## Why This Is Acceptable (and Intended)

CodeClone answers the question:

> “Do these pieces of code have the same structure and control flow?”

It does **not** answer:

> “Do these pieces of code behave identically at runtime?”

CFG v1 is intentionally **structural, conservative, and explainable**.

---

## Future Directions (CFG v2+)

Potential future enhancements:

- richer exception-flow modeling,
- optional data-flow fingerprints,
- configurable strictness modes.

These are considered **optional extensions**, not requirements for effective clone detection.

---

## Summary

- CFG v1 is a **structural abstraction**, not a runtime model.
- It is optimized for **clone detection**, not program verification.
- Its limitations are **intentional design trade-offs**.

This design keeps CodeClone effective, predictable, and CI-friendly.
