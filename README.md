# CodeClone

[![PyPI](https://img.shields.io/pypi/v/codeclone.svg?style=flat-square)](https://pypi.org/project/codeclone/)
[![Downloads](https://img.shields.io/pypi/dm/codeclone.svg?style=flat-square)](https://pypi.org/project/codeclone/)
[![tests](https://github.com/orenlab/codeclone/actions/workflows/tests.yml/badge.svg?branch=main&style=flat-square)](https://github.com/orenlab/codeclone/actions/workflows/tests.yml)
[![Python](https://img.shields.io/pypi/pyversions/codeclone.svg?style=flat-square)](https://pypi.org/project/codeclone/)
![CI First](https://img.shields.io/badge/CI-first-green?style=flat-square)
![Baseline](https://img.shields.io/badge/baseline-versioned-green?style=flat-square)
[![License](https://img.shields.io/pypi/l/codeclone.svg?style=flat-square)](LICENSE)

**CodeClone** is a Python code clone detector based on **normalized AST and Control Flow Graphs (CFG)**.  
It discovers architectural duplication and prevents new copy-paste from entering your codebase via CI.

---

## Why CodeClone

CodeClone focuses on **architectural duplication**, not text similarity. It detects structural patterns through:

- **Normalized AST analysis** — robust to renaming, formatting, and minor refactors
- **Control Flow Graphs** — captures execution logic, not just syntax
- **Strict, explainable matching** — clear signals, not fuzzy heuristics

Unlike token-based tools, CodeClone compares **structure and control flow**, making it ideal for finding:

- Repeated service/orchestration patterns
- Duplicated guard/validation blocks
- Copy-pasted handler logic across modules
- Recurring internal segments in large functions

---

## Core Capabilities

**Three Detection Levels:**

1. **Function clones (CFG fingerprint)**  
   Strong structural signal for cross-layer duplication

2. **Block clones (statement windows)**  
   Detects repeated local logic patterns

3. **Segment clones (report-only)**  
   Internal function repetition for explainability; not used for baseline gating

**CI-Ready Features:**

- Deterministic output with stable ordering
- Reproducible artifacts for audit trails
- Baseline-driven gating to prevent new duplication
- Fast incremental analysis with intelligent caching

---

## Installation

```bash
pip install codeclone
```

**Requirements:** Python 3.10+

---

## Quick Start

### Basic Analysis

```bash
# Analyze current directory
codeclone .

# Check version
codeclone --version
```

### Generate Reports

```bash
codeclone . \
  --html .cache/codeclone/report.html \
  --json .cache/codeclone/report.json \
  --text .cache/codeclone/report.txt
```

### CI Integration

```bash
# 1. Generate baseline once (commit to repo)
codeclone . --update-baseline

# 2. Add to CI pipeline
codeclone . --ci
```

The `--ci` preset is equivalent to `--fail-on-new --no-color --quiet`.

---

## Baseline Workflow

Baselines capture the **current state of duplication** in your codebase. Once committed, they serve as the reference
point for CI checks.

**Key points (contract-level):**

- Baseline file is versioned (`codeclone.baseline.json`) and used to classify clones as **NEW** vs **KNOWN**.
- Compatibility is gated by `schema_version`, `fingerprint_version`, and `python_tag`.
- Baseline trust is gated by `meta.generator.name` (`codeclone`) and integrity (`payload_sha256`).
- In CI preset (`--ci`), an untrusted baseline is a contract error (exit `2`).

Full contract details: [`docs/book/06-baseline.md`](docs/book/06-baseline.md)

---

## Exit Codes

CodeClone uses a deterministic exit code contract:

| Code | Meaning                                                                     |
|------|-----------------------------------------------------------------------------|
| `0`  | Success — run completed without gating failures                             |
| `2`  | Contract error — baseline missing/untrusted, invalid output extensions, incompatible versions, unreadable source files in CI/gating |
| `3`  | Gating failure — new clones detected or threshold exceeded                  |
| `5`  | Internal error — unexpected exception                                       |

**Priority:** Contract errors (`2`) override gating failures (`3`) when both occur.

Full contract details: [`docs/book/03-contracts-exit-codes.md`](docs/book/03-contracts-exit-codes.md)

**Debug Support:**

```bash
# Show detailed error information
codeclone . --debug

# Or via environment variable
CODECLONE_DEBUG=1 codeclone .
```

---

## Reports

### Supported Formats

- **HTML** (`--html`) — Interactive web report with filtering
- **JSON** (`--json`) — Machine-readable structured data
- **Text** (`--text`) — Plain text summary

### Report Schema (JSON v1.1)

The JSON report uses a compact deterministic layout:

- Top-level: `meta`, `files`, `groups`, `groups_split`, `group_item_layout`
- Optional top-level: `facts`
- `groups_split` provides explicit **NEW / KNOWN** separation per section
- `meta.groups_counts` provides deterministic per-section aggregates
- `meta` follows a shared canonical contract across HTML/JSON/TXT

Canonical report contract: [`docs/book/08-report.md`](docs/book/08-report.md)

**Minimal shape (v1.1):**

```json
{
  "meta": {
    "report_schema_version": "1.1",
    "codeclone_version": "1.4.0",
    "python_version": "3.13",
    "python_tag": "cp313",
    "baseline_path": "/path/to/codeclone.baseline.json",
    "baseline_fingerprint_version": "1",
    "baseline_schema_version": "1.0",
    "baseline_python_tag": "cp313",
    "baseline_generator_name": "codeclone",
    "baseline_generator_version": "1.4.0",
    "baseline_payload_sha256": "<sha256>",
    "baseline_payload_sha256_verified": true,
    "baseline_loaded": true,
    "baseline_status": "ok",
    "cache_path": "/path/to/.cache/codeclone/cache.json",
    "cache_used": true,
    "cache_status": "ok",
    "cache_schema_version": "1.2",
    "files_skipped_source_io": 0,
    "groups_counts": {
      "functions": {
        "total": 0,
        "new": 0,
        "known": 0
      },
      "blocks": {
        "total": 0,
        "new": 0,
        "known": 0
      },
      "segments": {
        "total": 0,
        "new": 0,
        "known": 0
      }
    }
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
      "loc_bucket"
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
  }
}
```

---

## Cache

Cache is an optimization layer only and is never a source of truth.

- Default path: `<root>/.cache/codeclone/cache.json`
- Schema version: **v1.2**
- Invalid or oversized cache is ignored with warning and rebuilt (fail-open)

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
- A CI guard against new duplication
- A deterministic analysis tool with auditable outputs

### CodeClone Is Not

- A linter or code formatter
- A semantic equivalence prover
- A runtime execution analyzer

---

## How It Works

**High-level Pipeline:**

1. **Parse** — Python source → AST
2. **Normalize** — AST → canonical structure
3. **CFG Construction** — per-function control flow graph
4. **Fingerprinting** — stable hash computation
5. **Grouping** — function/block/segment clone groups
6. **Determinism** — stable ordering for reproducibility
7. **Baseline Comparison** — new vs known clones (when requested)

Learn more:

- Architecture: [`docs/architecture.md`](docs/architecture.md)
- CFG semantics: [`docs/cfg.md`](docs/cfg.md)

---

## Documentation Map

Use this map to pick the right level of detail:

- **Contract book (canonical contracts/specs):** [`docs/book/`](docs/book/)
    - Start here: [`docs/book/00-intro.md`](docs/book/00-intro.md)
    - Exit codes and precedence: [`docs/book/03-contracts-exit-codes.md`](docs/book/03-contracts-exit-codes.md)
    - Baseline contract (schema/trust/integrity): [`docs/book/06-baseline.md`](docs/book/06-baseline.md)
    - Cache contract (schema/integrity/fail-open): [`docs/book/07-cache.md`](docs/book/07-cache.md)
    - Report contract (schema v1.1 + NEW/KNOWN split): [`docs/book/08-report.md`](docs/book/08-report.md)
    - CLI behavior: [`docs/book/09-cli.md`](docs/book/09-cli.md)
    - HTML rendering: [`docs/book/10-html-render.md`](docs/book/10-html-render.md)
    - Determinism policy: [`docs/book/12-determinism.md`](docs/book/12-determinism.md)
    - Compatibility/versioning rules: [
      `docs/book/14-compatibility-and-versioning.md`](docs/book/14-compatibility-and-versioning.md)
- **Deep dives:**
    - Architecture narrative: [`docs/architecture.md`](docs/architecture.md)
    - CFG semantics: [`docs/cfg.md`](docs/cfg.md)

## Links

- **Issues:** <https://github.com/orenlab/codeclone/issues>
- **PyPI:** <https://pypi.org/project/codeclone/>
