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
- Uses deterministic sorted traversal.
- Skips paths that resolve outside the root (symlink traversal guard).
- Applies cache-based skipping using file stat signatures.
- Default cache location is project-local: `<root>/.cache/codeclone/cache.json`
  (override via `--cache-path`, legacy alias: `--cache-dir`).
- Cache file size guard is configurable via `--max-cache-size-mb` (oversized cache is ignored with warning).
- Cache is best-effort: signature/version/shape mismatches are ignored with warnings, and
  invalid entries are skipped deterministically.

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
- symbolic call targets are preserved (to avoid API conflation)
- syntactic sugar (e.g. `x += 1` → `x = x + 1`)
- commutative operand canonicalization (`+`, `*`, `|`, `&`, `^`) on proven constant domains
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
- Preserves `match case` and `except` handler order structurally.
- Models `break` / `continue` as terminating loop transitions.
- Preserves `for/while ... else` semantics.

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
- Report UX merges overlapping segment windows and suppresses boilerplate‑only groups.
- A segment group is reported only if it has at least **2** unique statement types
  or contains a control‑flow statement.

---

## 8. Reporting

Detected clone groups can be:

- printed as text,
- exported as JSON,
- rendered as an interactive HTML report.

All report formats include provenance metadata:

- `codeclone_version`
- `python_version`
- `baseline_path`
- `baseline_fingerprint_version`
- `baseline_schema_version`
- `baseline_python_tag`
- `baseline_generator_version`
- `baseline_loaded`
- `baseline_status`
  (`ok | missing | too_large | invalid_json | invalid_type | missing_fields | mismatch_schema_version | mismatch_fingerprint_version | mismatch_python_version | generator_mismatch | integrity_missing | integrity_failed`)

Explainability contract (v1):

- Explainability facts are produced only by Python core/report layer.
- HTML/JS renderer is display-only and must not recalculate metrics or introduce new semantics.
- UI can format, filter, and highlight facts, but cannot invent new hints.

---

## CI Integration

Baseline comparison allows CI to fail **only on new clones**,
enabling gradual architectural improvement.

Baseline files use a stable v1 contract. Compatibility is tied to
`fingerprint_version` (normalize/CFG/hash pipeline), not package patch/minor version.
Regeneration is required when `fingerprint_version` changes.
Baseline integrity is tamper-evident via canonical `payload_sha256`.

Baseline validation order is deterministic:

1. size guard (before JSON parse),
2. JSON parse and root object/type checks,
3. required fields and type checks,
4. compatibility checks (`generator`, `schema_version`, `fingerprint_version`, `python_tag`),
5. integrity checks (`payload_sha256`).

Baseline loading is strict: schema/type violations, integrity failures, generator mismatch,
or oversized files are treated as untrusted input.
In `--ci` (or explicit `--fail-on-new`), untrusted baseline states fail fast.
Outside gating mode, untrusted baseline is ignored with warning and comparison proceeds
against an empty baseline.
Baseline size guard is configurable via `--max-baseline-size-mb`.

CLI exit code contract:

- `0` success
- `2` contract error (invalid arguments/output options or untrusted baseline in gating mode)
- `3` gating failure (`--ci` new clones, or `--fail-threshold` exceeded)
- `5` unexpected internal error (reserved)

`5` is reserved only for unexpected internal exception paths (tool bug), not for
baseline/options contract violations.

## Python Tag Consistency for Baseline Checks

Due to inherent AST differences across interpreter builds, baseline compatibility
is pinned to `python_tag` (for example `cp313`).

This preserves deterministic and reproducible clone detection results while allowing
patch updates within the same interpreter tag.

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
