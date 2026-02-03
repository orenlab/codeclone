# CodeClone

[![PyPI](https://img.shields.io/pypi/v/codeclone.svg)](https://pypi.org/project/codeclone/)
[![Downloads](https://img.shields.io/pypi/dm/codeclone.svg)](https://pypi.org/project/codeclone/)
[![tests](https://github.com/orenlab/codeclone/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/orenlab/codeclone/actions/workflows/tests.yml)
[![Python](https://img.shields.io/pypi/pyversions/codeclone.svg)](https://pypi.org/project/codeclone/)
[![License](https://img.shields.io/pypi/l/codeclone.svg)](LICENSE)

**CodeClone** is a Python code clone detector based on **normalized AST and control-flow graphs (CFG)**.
It helps teams discover architectural duplication and prevent new copy-paste from entering the codebase via CI.

CodeClone is designed to help teams:

- discover **structural and control-flow duplication**,
- identify architectural hotspots,
- prevent *new* duplication via CI and pre-commit hooks.

Unlike token- or text-based tools, CodeClone operates on **normalized Python AST and CFG**, making it robust against
renaming,
formatting, and minor refactoring.

---

## Why CodeClone?

Most existing tools detect *textual* duplication.
CodeClone detects **structural and block-level duplication**, which usually signals missing abstractions or
architectural drift.

Typical use cases:

- duplicated service or orchestration logic across layers (API ↔ application),
- repeated validation or guard blocks,
- copy-pasted request / handler flows,
- duplicated control-flow logic in routers, handlers, or services.

---

## Features

### Function-level clone detection (Type-2, CFG-based)

- Detects functions and methods with identical **control-flow structure**.
- Based on **Control Flow Graph (CFG)** fingerprinting.
- Robust to:
    - variable renaming,
    - constant changes,
    - attribute renaming,
    - formatting differences,
    - docstrings and type annotations.
- Ideal for spotting architectural duplication across layers.

### Block-level clone detection (Type-3-lite)

- Detects repeated **statement blocks** inside larger functions.
- Uses sliding windows over CFG-normalized statement sequences.
- Targets:
    - validation blocks,
    - guard clauses,
    - repeated orchestration logic.
- Carefully filtered to reduce noise:
    - no overlapping windows,
    - no clones inside the same function,
    - no `__init__` noise,
    - size and statement-count thresholds.

### Control-Flow Awareness (CFG v1)

- Each function is converted into a **Control Flow Graph**.
- CFG nodes contain normalized AST statements.
- CFG edges represent structural control flow:
    - `if` / `else`
    - `for` / `async for` / `while`
    - `try` / `except` / `finally`
    - `with` / `async with`
    - `match` / `case` (Python 3.10+)
- Current CFG semantics (v1):
    - `break` and `continue` are treated as statements (no jump targets),
    - after-blocks are explicit and always present,
    - focus is on **structural similarity**, not precise runtime semantics.

This design keeps clone detection **stable, deterministic, and low-noise**.

### Low-noise by design

- AST + CFG normalization instead of token matching.
- Conservative defaults tuned for real-world Python projects.
- Explicit thresholds for size and statement count.
- Focus on *architectural duplication*, not micro-similarities.

### CI-friendly baseline mode

- Establish a baseline of existing clones.
- Fail CI **only when new clones are introduced**.
- Safe for legacy codebases and incremental refactoring.

---

## Installation

```bash
pip install codeclone
```

Python **3.10+** is required.

---

## Quick Start

Run on a project:

```bash
codeclone .
```

This will:

- scan Python files,
- build CFGs for functions,
- detect function-level and block-level clones,
- print a summary to stdout.

Generate reports:

```bash
codeclone . \
  --json .cache/codeclone/report.json \
  --text .cache/codeclone/report.txt
```

Generate an HTML report:

```bash
codeclone . --html .cache/codeclone/report.html
```

---

## Baseline Workflow (Recommended)

### 1. Create a baseline

Run once on your current codebase:

```bash
codeclone . --update-baseline
```

Commit the generated baseline file to the repository.

### 2. Use in CI

```bash
codeclone . --fail-on-new
```

Behavior:

- ✅ existing clones are allowed,
- ❌ build fails if *new* clones appear,
- ✅ refactoring that removes duplication is always allowed.

Note on Python versions:

- AST dumps can differ across Python versions.
- For deterministic baselines, run baseline generation and CI checks on the
  same Python version.
- Baseline files include the Python version used to generate them, and
  `--fail-on-new` enforces a matching interpreter.

### Python Version Consistency for Baseline Checks

Due to inherent differences in Python’s AST between interpreter versions, baseline
generation and verification must be performed using the same Python version.

This ensures deterministic and reproducible clone detection results.

CI checks therefore pin baseline verification to a single Python version, while the
test matrix continues to validate compatibility across Python 3.10–3.14.

---

## Using with pre-commit

```yaml
repos:
  - repo: local
    hooks:
      - id: codeclone
        name: CodeClone
        entry: codeclone
        language: python
        args: [ ".", "--fail-on-new" ]
        types: [ python ]
```

---

## What CodeClone Is (and Is Not)

### CodeClone **is**

- an architectural analysis tool,
- a duplication radar,
- a CI guard against copy-paste,
- a control-flow-aware clone detector.

### CodeClone **is not**

- a linter,
- a formatter,
- a semantic equivalence prover,
- a runtime analyzer.

---

## How It Works (High Level)

1. Parse Python source into AST.
2. Normalize AST (names, constants, attributes, annotations).
3. Build a **Control Flow Graph (CFG)** per function.
4. Compute stable CFG fingerprints.
5. Detect function-level and block-level clones.
6. Apply conservative filters to suppress noise.

See the architectural overview:

- [docs/architecture.md](docs/architecture.md)

---

## Control Flow Graph (CFG)

Starting from **version 1.1.0**, CodeClone uses a **Control Flow Graph (CFG)**
to improve structural clone detection robustness.

The CFG is a **structural abstraction**, not a runtime execution model.

See full design and semantics:

- [docs/cfg.md](docs/cfg.md)

---

## License

MIT License
