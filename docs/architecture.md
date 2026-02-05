# CodeClone Architecture

This document describes the high-level architecture of **CodeClone**.

---

## Pipeline Overview

CodeClone processes Python projects in the following stages:

1. **Source scanning**
2. **AST parsing**
3. **AST normalization**
4. **CFG construction**
5. **Fingerprinting**
6. **Segment window extraction**
7. **Clone grouping**
8. **Reporting / CI decision**

---

## 1. Source Scanning

- Recursively scans `.py` files.
- Applies cache-based skipping using file stat signatures.
- Default cache location is project‑local: `<root>/.cache/codeclone/cache.json` (override via `--cache-dir`).

---

## 2. AST Parsing

- Uses Python's built-in `ast` module.
- Supports Python 3.10+ syntax.

---

## 3. AST Normalization

Normalization removes non-structural noise:

- variable names → `_VAR_`
- constants → `_CONST_`
- attributes → `_ATTR_`
- syntactic sugar (e.g. `x += 1` → `x = x + 1`)
- commutative operand canonicalization (`+`, `*`, `|`, `&`, `^`) when side‑effect free
- local logical equivalence (`not (x in y)` → `x not in y`, `not (x is y)` → `x is not y`)
- docstrings removed
- type annotations removed

This ensures structural stability across refactors.

---

## 4. CFG Construction

- Built per-function using `CFGBuilder`.
- Produces deterministic basic blocks.
- Captures structural control flow (`if`, `for`, `while`, `try`, `with`, `match`).
- Models short‑circuit `and`/`or` as micro‑CFG branches.
- Links `try/except` only from statements that may raise.

📄 See [docs/cfg.md](cfg.md) for full semantics.

---

## 5. Fingerprinting

Each function CFG is converted into a canonical string form and hashed.

This fingerprint is used to group structurally identical functions.

---

## 6. Segment Windows

Large functions are also scanned with **segment windows** (sliding windows over normalized
statements). These are used to detect **internal clones** inside the same function.

Segment windows are **never** used as a final equivalence signal; they are candidate
generators with strict hash confirmation.

---

## 7. Clone Detection

Two clone types are detected:

### Function clones (Type-2)

- Entire function CFGs are identical.

### Block clones (Type-3-lite)

- Repeated structural statement blocks inside larger functions.

Noise filters applied:

- minimum LOC / statement thresholds
- no overlapping blocks
- no same-function block clones
- `__init__` excluded from block analysis

---

### Segment clones (internal)

- Detected only **inside the same function**.
- Used for internal copy‑paste discovery and report explainability.
- Not included in baseline or CI failure logic.

---

## 8. Reporting

Detected clone groups can be:

- printed as text,
- exported as JSON,
- rendered as an interactive HTML report.

---

## CI Integration

Baseline comparison allows CI to fail **only on new clones**,
enabling gradual architectural improvement.

Baseline files are **versioned**. The baseline stores the CodeClone version and schema
version used to generate it. Mismatches result in a hard stop and require regeneration.

## Python Version Consistency for Baseline Checks

Due to inherent differences in Python’s AST between interpreter versions, baseline
generation and verification must be performed using the same Python version.

This ensures deterministic and reproducible clone detection results.

CI checks therefore pin baseline verification to a single Python version, while the
test matrix continues to validate compatibility across Python 3.10–3.14.

---

## Design Principles

- Structural > textual
- Deterministic > precise
- Low-noise > completeness
- CI-first design

---

## Summary

CodeClone is an **architectural duplication radar**,
not a static analyzer or linter.
