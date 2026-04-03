# CodeClone Architecture

> Scope note: this file is an architecture narrative/deep-dive.
> Contract-level guarantees (schemas, statuses, exit codes, trust model, determinism) are defined in `docs/book/`.

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

Clone groups are detected at three granularities:

### Function clone groups

- Grouped by `fingerprint|loc_bucket`.
- Report typing is deterministic (`Type-1`..`Type-4`) in report layer.

### Block clone groups

- Repeated structural statement windows across functions.
- Report typing is `Type-4` with explainability facts from core.

Noise filters applied:

- minimum LOC / statement thresholds
- no overlapping blocks
- no same-function block clones
- `__init__` excluded from block analysis

---

### Segment clones (internal/report-only)

- Detected only **inside the same function**.
- Used for internal copy‑paste discovery and report explainability.
- Not included in baseline or CI failure logic.
- Report UX merges overlapping segment windows and suppresses boilerplate‑only groups.
- A segment group is reported only if it has at least **2** unique statement types
  or contains a control‑flow statement.

---

### Structural findings (report-only)

- `duplicated_branches`: repeated branch-body signatures.
- `clone_guard_exit_divergence`: guard/terminal divergence inside one function-clone cohort.
- `clone_cohort_drift`: drift from majority terminal/guard/try/side-effect profile.

These findings are rendered in reports only and do not change baseline diff or CI
gating decisions.

---

## 8. Reporting

Detected findings can be rendered as:

- interactive HTML (`--html`),
- canonical JSON (`--json`, schema `2.3`),
- deterministic text projection (`--text`),
- deterministic Markdown projection (`--md`),
- deterministic SARIF projection (`--sarif`).

Reporting uses a layered model:

- canonical sections: `report_schema_version`, `meta`, `inventory`, `findings`, `metrics`
- non-canonical view layer: `derived`
- integrity metadata: `integrity` (`canonicalization` + `digest`)

Provenance is carried through `meta` and includes:

- runtime/context (`codeclone_version`, `python_version`, `python_tag`, `analysis_mode`, `report_mode`)
- analysis thresholds (`meta.analysis_thresholds.design_findings`)
- baseline status block (`meta.baseline.*`)
- cache status block (`meta.cache.*`)
- metrics-baseline status block (`meta.metrics_baseline.*`)
- generation timestamp (`meta.runtime.report_generated_at_utc`)

Explainability contract (v1):

- Explainability facts are produced only by Python core/report layer.
- HTML/JS renderer is display-only and must not recalculate metrics or introduce new semantics.
- UI can format, filter, and highlight facts, but cannot invent new hints.

---

## 9. MCP Agent Interface

CodeClone also exposes an optional MCP layer for AI agents and MCP-capable
clients.

Current shape:

- install via the optional `codeclone[mcp]` extra
- launch via `codeclone-mcp`
- transports:
    - `stdio`
    - `streamable-http`
- semantics:
    - read-only
    - baseline-aware
    - built on the same pipeline/report contracts as the CLI
    - bounded in-memory run history

Operational note:

- `codeclone/mcp_server.py` is only a thin launcher/registration layer.
- The optional MCP runtime is imported lazily so the base `codeclone` install
  and normal CI paths do not require MCP packages.
- `codeclone/mcp_service.py` is the in-process adapter over the existing
  pipeline/report contracts.

The MCP layer is intentionally thin. It does not add a separate analysis engine;
it adapts the existing pipeline into tools/resources such as:

- analyze repository
- analyze changed paths
- get run summary
- compare runs
- list findings
- inspect one finding
- project remediation payloads
- list hotspots
- generate PR summary
- preview gate outcomes
- keep session-local reviewed markers

This keeps agent integrations deterministic and aligned with the same canonical
report document used by JSON/HTML/SARIF.

Security boundaries:

- Read-only by design — no tool mutates source files, baselines, or repo state.
- `--allow-remote` guard required for non-local transports; default is `stdio`.
- `cache_policy=refresh` rejected to preserve read-only semantics.
- Review markers are session-local in-memory state, never persisted.
- Run history bounded by `--history-limit` to prevent unbounded memory growth.
- `git_diff_ref` validated against strict regex to prevent injection.

---

## CI Integration

Baseline comparison allows CI to fail **only on new clones**,
enabling gradual architectural improvement.

Baseline files use a stable v2 contract (schema `2.0`, with compatibility
support for major `1` legacy schema checks where applicable). Compatibility is checked by
`schema_version`, `fingerprint_version`, `python_tag`, and `generator.name`,
not package patch/minor version.
Regeneration is typically required when `fingerprint_version` or `python_tag` changes.
Baseline integrity is tamper-evident via canonical `payload_sha256`, which covers
`clones.functions`, `clones.blocks`, `meta.fingerprint_version`, and `meta.python_tag`.
`schema_version` and `generator.name` are compatibility gates and intentionally
excluded from the integrity hash.
`created_at` and `generator.version` are informational metadata and do not affect
integrity validation.

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
- `2` contract error (invalid arguments/output options, untrusted baseline, or unreadable source files in gating mode)
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

CodeClone provides **structural code quality analysis** for Python —
clone detection, quality metrics, and baseline-aware CI governance.
