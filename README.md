<p align="center">
  <img src="docs/assets/codeclone-wordmark.svg" alt="CodeClone" height="48">
</p>

<p align="center">
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/v/codeclone.svg?style=flat-square" alt="PyPI"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/dm/codeclone.svg?style=flat-square" alt="Downloads"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/tests.yml"><img src="https://github.com/orenlab/codeclone/actions/workflows/tests.yml/badge.svg?branch=main&style=flat-square" alt="Tests"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/pyversions/codeclone.svg?style=flat-square" alt="Python"></a>
  <img src="https://img.shields.io/badge/codeclone-B-green?style=flat-square" alt="CodeClone Quality">
  <img src="https://img.shields.io/badge/CI-first-green?style=flat-square" alt="CI First">
  <img src="https://img.shields.io/badge/baseline-versioned-green?style=flat-square" alt="Baseline">
  <a href="LICENSE"><img src="https://img.shields.io/pypi/l/codeclone.svg?style=flat-square" alt="License"></a>
</p>

**CodeClone** is a Python structural clone detector, baseline-aware governance tool, and code-health gate built on
**normalized AST** and **Control Flow Graphs (CFG)**.

It finds **architectural duplication**, shows the **matched code directly**, and helps teams keep CI strict about **new
** duplication and quality regressions without re-litigating already accepted technical debt.

CodeClone favors **deterministic structural evidence** over fuzzy similarity heuristics, producing results that are more
**explainable, reviewable, and auditable** in real CI workflows.

---

## Why CodeClone

CodeClone focuses on **architectural duplication**, not text similarity.

It detects structural patterns through:

- **Normalized AST analysis** — robust to renaming, formatting, and minor refactors
- **Control Flow Graphs** — captures execution logic, not just syntax
- **Strict, explainable matching** — clear signals instead of fuzzy heuristics
- **Baseline-aware governance** — existing duplication can be accepted as known technical debt, while CI blocks only
  newly introduced clones

Unlike token-based duplicate detectors, CodeClone compares **structure and control flow**, which makes it well suited
for finding:

- Repeated service or orchestration patterns
- Duplicated guard and validation blocks
- Copy-pasted handler logic across modules
- Recurring internal segments in large functions

Unlike threshold-only quality gates, CodeClone supports **baseline-aware clone governance**: historical duplication can
be recorded as **KNOWN**, while CI stays strict about **NEW** duplication and regressions.

---

## Core Capabilities

### Clone Detection

CodeClone detects duplication at three levels:

1. **Function clones (CFG fingerprint)**  
   Strong structural signal for cross-layer duplication

2. **Block clones (statement windows)**  
   Detect repeated local logic patterns

3. **Segment clones (report-only)**  
   Internal function repetition for explainability; not used for baseline gating

### Code Health and CI

CodeClone 2.0 expands from clone detection into a broader **code-health workflow** for CI:

- Deterministic output with stable ordering
- Reproducible artifacts for audit trails
- Baseline-driven gating to prevent new duplication
- Rich reports with **NEW / KNOWN** split and direct matched code snippets
- Report provenance for CI: scan identity, baseline status, integrity, and cache status
- Fast incremental analysis with intelligent caching
- Quality metrics pipeline: complexity (CC), coupling (CBO), cohesion (LCOM4), dependency cycles, dead code, and health
  score
- Metrics-aware gates: threshold-based and **NEW-vs-baseline** checks
- Unified baseline flow: clone baseline can store embedded top-level `metrics`
- Prioritized suggestions in report outputs
- Operational CLI summary: analyzed lines, functions, methods, and classes per run
- Dead-code liveness ignores references from test files, so symbols used only in tests remain actionable dead-code
  candidates

In practice, CodeClone acts both as a **structural clone detector** and as a **deterministic code-health gate** for CI.

### Compatibility and Contract Stability

CodeClone treats **baseline and fingerprint compatibility as a strict user-facing contract**.

- Baseline schema can evolve independently from clone identity
- CodeClone v2 bumps the baseline schema to `2.0` while preserving `fingerprint_version = "1"`
- Backward compatibility with legacy clone-only baseline payloads remains supported
- Schema evolution may extend payloads, but clone identity remains stable unless a deliberate fingerprint contract
  change is declared
- Any analysis change that could alter clone identity is treated as a contract-sensitive change

This matters in fast-moving projects: teams can upgrade CodeClone frequently without re-accepting historical technical
debt or destabilizing CI behavior.

---

## Installation

```bash
pip install codeclone

# or with uv
uv tool install codeclone
```

**Requirements:** Python 3.10+

---

## Quick Start

### Basic Analysis

```bash
# Analyze current directory
codeclone .

# Show version
codeclone --version
```

### Run via uv (without install)

```bash
uvx codeclone@latest .
```

### Generate Reports

```bash
codeclone . \
  --html .cache/codeclone/report.html \
  --json .cache/codeclone/report.json \
  --text .cache/codeclone/report.txt
```

You can also pass report flags without paths to use deterministic defaults:

```bash
codeclone . --html --json --text
# writes to:
# .cache/codeclone/report.html
# .cache/codeclone/report.json
# .cache/codeclone/report.txt
```

### CI Integration

```bash
# 1. Generate baseline once and commit it to the repository
codeclone . --update-baseline

# 2. Add the check to CI
codeclone . --ci
```

The `--ci` preset is equivalent to `--fail-on-new --no-color --quiet`.

### Metrics and Gating Examples

```bash
# Unified baseline update (clones + metrics in full mode)
codeclone . --update-baseline

# Metrics threshold gates
codeclone . --fail-complexity 20 --fail-coupling 10 --fail-cohesion 4 --fail-health 60

# Structural policy gates
codeclone . --fail-cycles --fail-dead-code

# Gate only on NEW metric regressions vs metrics baseline snapshot
codeclone . --fail-on-new-metrics

# Clone-only compatibility mode (skip all metrics stages)
codeclone . --skip-metrics
```

---

## Configuration via pyproject.toml

CodeClone can load project defaults from `pyproject.toml` under `[tool.codeclone]`.

```toml
[tool.codeclone]
min_loc = 20
min_stmt = 8
baseline = "codeclone.baseline.json"
skip_metrics = false
quiet = true

# optional report targets
html_out = ".cache/codeclone/report.html"
json_out = ".cache/codeclone/report.json"
text_out = ".cache/codeclone/report.txt"
```

Effective precedence is deterministic:

1. Explicit CLI flags
2. `[tool.codeclone]` from `pyproject.toml`
3. Built-in defaults

Path values from `pyproject.toml` are resolved relative to the scan root.

Full config contract: [`docs/book/04-config-and-defaults.md`](docs/book/04-config-and-defaults.md)

---

## Baseline Workflow

Baselines capture the **current state of duplication** in your codebase. Once committed, they become the reference point
for CI checks.

### Key Points

- Baseline files are versioned (`codeclone.baseline.json`) and used to classify clones as **NEW** vs **KNOWN**
- Baseline schema `2.0` supports optional top-level `metrics` in the same file
- Default `--metrics-baseline` path is the same as `--baseline` (`codeclone.baseline.json`)
- Compatibility is gated by `schema_version`, `fingerprint_version`, and `python_tag`
- Baseline trust is gated by `meta.generator.name` (`codeclone`) and integrity (`payload_sha256`)
- `--update-baseline` in full mode also updates the metrics baseline snapshot unless metrics are skipped
- Standalone metrics baseline path remains supported via `--metrics-baseline PATH`
- In CI preset mode (`--ci`), an untrusted baseline is treated as a contract error (exit `2`)

This model lets teams **accept existing technical debt without normalizing new debt**: known duplication stays recorded
in baseline, while CI remains strict about newly introduced clones and regressions.

Full contract details: [`docs/book/06-baseline.md`](docs/book/06-baseline.md)

---

## Exit Codes

CodeClone uses a deterministic exit code contract:

| Code | Meaning                                                                                                                                |
|------|----------------------------------------------------------------------------------------------------------------------------------------|
| `0`  | Success — run completed without gating failures                                                                                        |
| `2`  | Contract error — baseline missing or untrusted, invalid output extensions, incompatible versions, unreadable source files in CI/gating |
| `3`  | Gating failure — clone gates (`--fail-on-new`, `--fail-threshold`) or metrics quality gates                                          |
| `5`  | Internal error — unexpected exception                                                                                                  |

**Priority:** Contract errors (`2`) override gating failures (`3`) when both occur.

Full contract details: [`docs/book/03-contracts-exit-codes.md`](docs/book/03-contracts-exit-codes.md)

### Debug Support

```bash
# Show detailed error information
codeclone . --debug

# Or via environment variable
CODECLONE_DEBUG=1 codeclone .
```

---

## Reports

### Supported Formats

- **HTML** (`--html`) — interactive multi-tab report with overview, clones, metrics, dependencies, dead code, and
  suggestions
- **JSON** (`--json`) — deterministic machine-readable contract payload
- **Text** (`--text`) — plain text report with provenance and **NEW / KNOWN** split

### Why the Reports Matter in CI

CodeClone reports are designed to be **reviewable**, not just machine-readable:

- Clone groups show the **matched code directly**, not only file ranges
- Reports preserve explicit **NEW / KNOWN** split for baseline-aware review
- Provenance captures scan identity, baseline metadata, integrity fields, and cache status
- Deterministic layouts make results easier to audit, diff, and trust in CI pipelines

### Report Schema (JSON v2.0)

The JSON report uses a compact deterministic layout:

- Required top-level: `report_schema_version`, `meta`, `files`, `groups`, `groups_split`, `group_item_layout`, `clones`,
  `clone_types`
- Optional top-level: `facts`, `metrics`, `suggestions`
- `groups_split` provides explicit **NEW / KNOWN** separation per section
- `meta.groups_counts` provides deterministic per-section aggregates
- `meta` follows a shared canonical contract across HTML, JSON, and TXT
- Report provenance includes scan identity, baseline metadata, integrity fields, and cache status
- Byte-identical comparisons require identical run config and provenance state (for example cache path/status/usage)

Canonical report contract: [`docs/book/08-report.md`](docs/book/08-report.md)

<details>
<summary><strong>Minimal shape (v2.0)</strong></summary>

```json
{
  "report_schema_version": "2.0",
  "meta": {
    "report_schema_version": "2.0",
    "project_name": "my-project",
    "scan_root": "/path/to/my-project"
  },
  "files": [],
  "groups": {
    "functions": {},
    "blocks": {},
    "segments": {}
  },
  "groups_split": {
    "functions": {
      "new": [],
      "known": []
    },
    "blocks": {
      "new": [],
      "known": []
    },
    "segments": {
      "new": [],
      "known": []
    }
  },
  "group_item_layout": {
    "functions": [
      "file_i",
      "qualname",
      "start",
      "end",
      "loc",
      "stmt_count",
      "fingerprint",
      "loc_bucket",
      "cyclomatic_complexity",
      "nesting_depth",
      "risk",
      "raw_hash"
    ],
    "blocks": [
      "file_i",
      "qualname",
      "start",
      "end",
      "size"
    ],
    "segments": [
      "file_i",
      "qualname",
      "start",
      "end",
      "size",
      "segment_hash",
      "segment_sig"
    ]
  },
  "facts": {
    "blocks": {}
  },
  "metrics": {},
  "suggestions": []
}
```

</details>

---

## Cache

Cache is an optimization layer only. It is never a source of truth.

- Default path: `<root>/.cache/codeclone/cache.json`
- Schema version: **v2.0**
- Compatibility includes the analysis profile (`min_loc`, `min_stmt`)
- Invalid or oversized cache is ignored with a warning and rebuilt (fail-open)

Full contract details: [`docs/book/07-cache.md`](docs/book/07-cache.md)

---

## Pre-commit Integration

```yaml
repos:
  - repo: local
    hooks:
      - id: codeclone
        name: CodeClone
        entry: codeclone
        language: system
        pass_filenames: false
        args: [ ".", "--ci" ]
        types: [ python ]
```

---

## What CodeClone Is (and Is Not)

### CodeClone Is

- A structural clone detector for Python
- A baseline-aware CI gate for duplication and metric regressions
- A deterministic code-health tool with auditable outputs
- A contract-driven tool that treats compatibility across releases as a first-class concern

### CodeClone Is Not

- A linter or code formatter
- A semantic equivalence prover
- A runtime execution analyzer

---

## How It Works

### High-Level Pipeline

1. **Parse** — Python source to AST
2. **Normalize** — AST to canonical structure
3. **CFG Construction** — per-function control flow graph
4. **Fingerprinting** — stable hash computation
5. **Grouping** — function, block, and segment clone groups
6. **Metrics** — complexity, coupling, cohesion, dependencies, dead code, and health
7. **Determinism** — stable ordering for reproducibility
8. **Baseline Comparison** — new vs known clones and metric regressions (when requested)

Learn more:

- Architecture: [`docs/architecture.md`](docs/architecture.md)
- CFG semantics: [`docs/cfg.md`](docs/cfg.md)

---

## Documentation Map

Use this map to pick the right level of detail:

- **Contract book (canonical contracts/specs):** [`docs/book/`](docs/book/)
    - Start here: [`docs/book/00-intro.md`](docs/book/00-intro.md)
    - Exit codes and precedence: [`docs/book/03-contracts-exit-codes.md`](docs/book/03-contracts-exit-codes.md)
    - Baseline contract (schema, trust, integrity): [`docs/book/06-baseline.md`](docs/book/06-baseline.md)
    - Cache contract (schema, integrity, fail-open): [`docs/book/07-cache.md`](docs/book/07-cache.md)
    - Report contract (schema v2.0 + NEW/KNOWN split): [`docs/book/08-report.md`](docs/book/08-report.md)
    - CLI behavior: [`docs/book/09-cli.md`](docs/book/09-cli.md)
    - HTML rendering: [`docs/book/10-html-render.md`](docs/book/10-html-render.md)
    - Metrics mode and quality gates: [
      `docs/book/15-metrics-and-quality-gates.md`](docs/book/15-metrics-and-quality-gates.md)
    - Dead-code contract: [`docs/book/16-dead-code-contract.md`](docs/book/16-dead-code-contract.md)
    - Suggestions and clone typing: [
      `docs/book/17-suggestions-and-clone-typing.md`](docs/book/17-suggestions-and-clone-typing.md)
    - Determinism policy: [`docs/book/12-determinism.md`](docs/book/12-determinism.md)
    - Compatibility and versioning: [
      `docs/book/14-compatibility-and-versioning.md`](docs/book/14-compatibility-and-versioning.md)

- **Deep dives:**
    - Architecture narrative: [`docs/architecture.md`](docs/architecture.md)
    - CFG semantics: [`docs/cfg.md`](docs/cfg.md)

## Links

- **Issues:** <https://github.com/orenlab/codeclone/issues>
- **PyPI:** <https://pypi.org/project/codeclone/>
