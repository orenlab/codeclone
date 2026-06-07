<!-- doc-scope: HOW IT WORKS. class: explanation max-lines: 120
      NARRATIVE PIPELINE OVERVIEW — how CodeClone works.
     owns: pipeline stage descriptions, surfaces table, design principles.
     does-not-own: contract details (→ book/ chapters), MCP tools (→ guide/mcp/README.md),
       CFG semantics (→ book/04), report schema (→ book/05).
     rule: this is a MAP — 1-2 sentences per topic + link into Reference.
       Do not shadow-copy book chapters here. -->
# How CodeClone Works

> This page is a narrative architecture overview.
> Contract-level guarantees are defined in the
> [Contracts Book](../../book/README.md).

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
8. **Project metrics** (complexity, coupling, health, dead code, …)
9. **Canonical report assembly**
10. **Baseline diff and metric gating** (CI exit decision)

Full contract: [Core pipeline](../../book/03-core-pipeline.md).

---

## 1. Source Scanning

- Recursively scans `.py` files.
- Uses deterministic sorted traversal.
- Skips paths that resolve outside the root (symlink traversal guard).
- Applies cache-based skipping using file stat signatures.

Cache contract: [Cache](../../book/08-cache.md).

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
- Models short-circuit `and`/`or` as micro-CFG branches.
- Links `try/except` only from statements that may raise.
- Preserves `match case` and `except` handler order structurally.
- Models `break` / `continue` as terminating loop transitions.
- Preserves `for/while ... else` semantics.

Full semantics: [CFG Semantics](../../book/04-cfg-semantics.md).

---

## 5. Fingerprinting

Each function CFG is converted into a canonical string form and hashed.
This fingerprint is used to group structurally identical functions.

---

## 6. Segment Windows

Large functions are also scanned with **segment windows** (sliding windows over
normalized statements). These are used to detect **internal clones** inside the
same function.

Segment windows are **never** used as a final equivalence signal; they are
candidate generators with strict hash confirmation.

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

### Segment clones (internal/report-only)

- Detected only **inside the same function**.
- Used for internal copy-paste discovery and report explainability.
- Not included in baseline or CI failure logic.

### Structural findings (report-only)

- `duplicated_branches`: repeated branch-body signatures.
- `clone_guard_exit_divergence`: guard/terminal divergence inside one function-clone cohort.
- `clone_cohort_drift`: drift from majority terminal/guard/try/side-effect profile.

These findings are rendered in reports only and do not change baseline diff or CI
gating decisions.

---

## 8. Reporting

Detected findings can be rendered as interactive HTML, canonical JSON (schema
`2.11`), deterministic text, Markdown, or SARIF projections. Reporting is
separate from CI gating: report-only structural findings and segment clones do
not change baseline diff or gate evaluation.

Report contract: [Report](../../book/05-report.md).
HTML rendering: [HTML Render](../../book/06-html-render.md).

---

## 9. CI gating

After the canonical report is built, clone baseline diff and configured metric
gates decide exit code `3` when policy fails. Gating mode is active when any
`--fail-*`, `--ci`, or minimum-coverage threshold is set (see
[CLI](../../book/11-cli.md)). Unreadable source in gating mode is a contract
error (exit `2`, marker `CONTRACT ERROR:`) and takes priority over clone/metric
gate failure.

Exit codes: [09-exit-codes](../../book/09-exit-codes.md).

---

## Surfaces

Every output surface — CLI, HTML, MCP, IDE — is a projection of the same
canonical report. No surface adds a second analysis engine.

| Surface | Role | Contract |
|---------|------|----------|
| CLI | Scripting and CI | [CLI](../../book/11-cli.md) |
| MCP | Read-only agent/client integration | [MCP interface](../../book/25-mcp-interface/index.md) |
| VS Code | Guided IDE review | [VS Code](../integrations/vscode/setup.md) |
| Claude Desktop | Local `.mcpb` bundle | [Claude Desktop](../integrations/claude-desktop/setup.md) |
| Codex | Marketplace plugin with skills | [Codex](../integrations/codex/setup.md) |
| Cursor | Plugin with skills, rules, hooks | [Cursor](../integrations/cursor/install-and-skills.md) |
| SARIF | IDE code scanning | [SARIF](../integrations/sarif/export.md) |

---

## Design Principles

- Structural > textual
- Deterministic > precise
- Low-noise > completeness
- CI-first design

Module map: [Architecture Map](../../book/02-architecture-map.md).
