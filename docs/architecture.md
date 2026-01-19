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
6. **Clone grouping**
7. **Reporting / CI decision**

---

## 1. Source Scanning

- Recursively scans `.py` files.
- Applies cache-based skipping using file stat signatures.

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
- docstrings removed
- type annotations removed

This ensures structural stability across refactors.

---

## 4. CFG Construction

- Built per-function using `CFGBuilder`.
- Produces deterministic basic blocks.
- Captures structural control flow (`if`, `for`, `while`).

📄 See [docs/cfg.md](cfg.md) for full semantics.

---

## 5. Fingerprinting

Each function CFG is converted into a canonical string form and hashed.

This fingerprint is used to group structurally identical functions.

---

## 6. Clone Detection

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

## 7. Reporting

Detected clone groups can be:

- printed as text,
- exported as JSON,
- rendered as an interactive HTML report.

---

## CI Integration

Baseline comparison allows CI to fail **only on new clones**,
enabling gradual architectural improvement.

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
