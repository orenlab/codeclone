# CodeClone

**CodeClone** is an AST-based code clone detector for Python, focused on **architectural duplication**, not simple
copy-paste.

It is designed to help teams:

- discover structural and logical code duplication,
- understand architectural hotspots,
- and prevent *new* duplication from entering the codebase via CI.

Unlike token- or text-based tools, CodeClone works on **normalized Python AST**, which makes it robust against renaming,
formatting, and minor refactoring.

---

## Why CodeClone?

Most existing tools detect *textual* duplication.
CodeClone detects **structural and block-level duplication** that usually indicates missing abstractions or
architectural drift.

Typical use cases:

- duplicated service logic across layers (API ↔ application),
- repeated validation or guard blocks,
- copy-pasted request/handler flows,
- duplicated orchestration logic in routers, handlers, or services.

---

## Features

### Function-level clone detection (Type-2)

- Detects functions and methods with identical structure.
- Robust to:
    - variable renaming,
    - constant changes,
    - formatting differences.
- Ideal for spotting architectural duplication between layers.

### Block-level clone detection (Type-3-lite)

- Detects repeated **statement blocks** inside larger functions.
- Targets:
    - validation blocks,
    - guard clauses,
    - repeated orchestration logic.
- Carefully filtered to avoid noise:
    - no overlapping windows,
    - no clones inside the same function,
    - no `__init__` noise.

### Low-noise by design

- AST normalization instead of token matching.
- Size and statement-count thresholds.
- Conservative defaults tuned for real-world Python projects.

### CI-friendly baseline mode

- Establish a baseline of existing clones.
- Fail CI **only when new clones are introduced**.
- Safe for legacy codebases.

---

## Installation

```bash
pip install codeclone
```

Python 3.10+ is required.

⸻

Quick Start

Run on a project:

```bash
codeclone .
```

This will:

* scan Python files,
* detect function-level and block-level clones,
* print a summary to stdout.

Generate reports:

```bash
codeclone . \
  --json-out .cache/codeclone/report.json \
  --text-out .cache/codeclone/report.txt
```

⸻

Baseline Workflow (Recommended)

1. Create a baseline

Run once on your current codebase:

```bash
codeclone . --update-baseline
```

This creates a file:

```bash
.codeclone-baseline.json
```

Commit this file to the repository.

⸻

2. Use in CI

In CI, run:

```bash
codeclone . --fail-on-new
```

Behavior:

* ✅ existing clones are allowed,
* ❌ build fails if new function or block clones appear,
* ✅ refactoring that removes duplication is always allowed.

This enables gradual improvement without breaking existing development flow.

⸻

What CodeClone Is (and Is Not)

CodeClone is

* an architectural analysis tool,
* a duplication radar,
* a CI guard against copy-paste.

CodeClone is not

* a linter,
* a formatter,
* a replacement for SonarQube or static analyzers,
* a semantic equivalence prover.

It intentionally focuses on high-signal duplication.

⸻

How It Works (High Level)

* Parses Python source into AST.
* Normalizes:
    - variable names,
    - constants,
    - attributes,
    - docstrings and annotations.
* Computes stable structural fingerprints.
* Detects:
    - identical function structures,
    - repeated statement blocks across functions.
* Applies filters to suppress noise.

⸻

License

MIT License