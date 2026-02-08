# CodeClone

[![PyPI](https://img.shields.io/pypi/v/codeclone.svg?style=flat-square)](https://pypi.org/project/codeclone/)
[![Downloads](https://img.shields.io/pypi/dm/codeclone.svg?style=flat-square)](https://pypi.org/project/codeclone/)
[![tests](https://github.com/orenlab/codeclone/actions/workflows/tests.yml/badge.svg?branch=main&style=flat-square)](https://github.com/orenlab/codeclone/actions/workflows/tests.yml)
[![Python](https://img.shields.io/pypi/pyversions/codeclone.svg?style=flat-square)](https://pypi.org/project/codeclone/)
![CI First](https://img.shields.io/badge/CI-first-green?style=flat-square)
![Baseline](https://img.shields.io/badge/baseline-versioned-green?style=flat-square)
[![License](https://img.shields.io/pypi/l/codeclone.svg?style=flat-square)](LICENSE)

**CodeClone** is a Python code clone detector based on **normalized Python AST and Control Flow Graphs (CFG)**.
It helps teams discover architectural duplication and prevent new copy-paste from entering the codebase via CI.

CodeClone is designed to help teams:

- discover **structural and control-flow duplication**,
- identify architectural hotspots,
- prevent *new* duplication via CI and pre-commit hooks.

Unlike token- or text-based tools, CodeClone operates on **normalized Python AST and CFG**, making it robust against
renaming, formatting, and minor refactoring.

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

### Segment-level internal clone detection

- Detects repeated **segment windows** inside the same function.
- Uses a two-step deterministic match (candidate signature → strict hash).
- Included in reports for explainability, **not** in baseline/CI failure logic.

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
    - `and` / `or` are modeled as short-circuit micro-CFG branches,
    - `try/except` links only from statements that may raise,
    - `break` / `continue` are modeled as terminating loop transitions with explicit targets,
    - `for/while ... else` semantics are preserved structurally,
    - `match case` and `except` handler order is preserved structurally,
    - after-blocks are explicit and always present,
    - focus is on **structural similarity**, not precise runtime semantics.

This design keeps clone detection **stable, deterministic, and low-noise**.

### Low-noise by design

- AST + CFG normalization instead of token matching.
- Conservative defaults tuned for real-world Python projects.
- Explicit thresholds for size and statement count.
- No probabilistic scoring or heuristic similarity thresholds.
- Safe commutative normalization and local logical equivalences only.
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

Python 3.10+ is required.

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

Check version:

```bash
codeclone --version
```

---

## Reports and Metadata

All report formats include provenance metadata for auditability:

`codeclone_version`, `python_version`, `baseline_path`, `baseline_version`,
`baseline_schema_version`, `baseline_python_version`, `baseline_loaded`,
`baseline_status` (and cache metadata when available).

baseline_status values:

- `ok`
- `missing`
- `legacy`
- `invalid`
- `mismatch_version`
- `mismatch_schema`
- `mismatch_python`
- `generator_mismatch`
- `integrity_missing`
- `integrity_failed`
- `too_large`

---

## Baseline Workflow (Recommended)

1. Create a baseline

Run once on your current codebase:

```bash
codeclone . --update-baseline
```

Commit the generated baseline file to the repository.

Baselines are versioned. If CodeClone is upgraded, regenerate the baseline to keep
CI deterministic and explainable.

Baseline format in 1.3+ is tamper-evident (generator, payload_sha256) and validated
before baseline comparison.

2. Trusted vs untrusted baseline behavior

Baseline states considered untrusted:

- `invalid`
- `too_large`
- `generator_mismatch`
- `integrity_missing`
- `integrity_failed`

Behavior:

- in normal mode, untrusted baseline is ignored with a warning (comparison falls back to empty baseline);
- in `--fail-on-new` / `--ci`, untrusted baseline fails fast (exit code 2).

3. Use in CI

```bash
codeclone . --ci
```

or:

```bash
codeclone . --ci --html .cache/codeclone/report.html
```

`--ci` is equivalent to `--fail-on-new --no-color --quiet`.

Behavior:

- existing clones are allowed,
- the build fails if new clones appear,
- refactoring that removes duplication is always allowed.

`--fail-on-new` / `--ci` exits with a non-zero code when new clones are detected.

---

### Cache

By default, CodeClone stores the cache per project at:

```bash
<root>/.cache/codeclone/cache.json
```

You can override this path with `--cache-path` (`--cache-dir` is a legacy alias).

If you used an older version of CodeClone, delete the legacy cache file at
`~/.cache/codeclone/cache.json` and add `.cache/` to `.gitignore`.

Cache integrity checks are strict: signature mismatch or oversized cache files are ignored
with an explicit warning, then rebuilt from source.

Cache entries are validated against expected structure/types; invalid entries are ignored
deterministically.

---

## Python Version Consistency for Baseline Checks

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
        language: system
        pass_filenames: false
        args: [ ".", "--ci" ]
        types: [ python ]
```

---

## What CodeClone Is (and Is Not)

### CodeClone Is

- an architectural analysis tool,
- a duplication radar,
- a CI guard against copy-paste,
- a control-flow-aware clone detector.

### CodeClone Is Not

- a linter,
- a formatter,
- a semantic equivalence prover,
- a runtime analyzer.

## How It Works (High Level)

1. Parse Python source into AST.
2. Normalize AST (names, constants, attributes, annotations).
3. Build a Control Flow Graph (CFG) per function.
4. Compute stable CFG fingerprints.
5. Extract segment windows for internal clone discovery.
6. Detect function-level, block-level, and segment-level clones.
7. Apply conservative filters to suppress noise.

See the architectural overview:

- [docs/architecture.md](docs/architecture.md)

---

## Control Flow Graph (CFG)

Starting from version 1.1.0, CodeClone uses a Control Flow Graph (CFG)
to improve structural clone detection robustness.

The CFG is a structural abstraction, not a runtime execution model.

See full design and semantics:

- [docs/cfg.md](docs/cfg.md)

---

## CLI Options

| Option                        | Description                                                          | Default                              |
|-------------------------------|----------------------------------------------------------------------|--------------------------------------|
| `root`                        | Project root directory to scan                                       | `.`                                  |
| `--version`                   | Print CodeClone version and exit                                     | -                                    |
| `--min-loc`                   | Minimum function LOC to analyze                                      | `15`                                 |
| `--min-stmt`                  | Minimum AST statements to analyze                                    | `6`                                  |
| `--processes`                 | Number of worker processes                                           | `4`                                  |
| `--cache-path FILE`           | Cache file path                                                      | `<root>/.cache/codeclone/cache.json` |
| `--cache-dir FILE`            | Legacy alias for `--cache-path`                                      | -                                    |
| `--max-cache-size-mb MB`      | Max cache size before ignore + warning                               | `50`                                 |
| `--baseline FILE`             | Baseline file path                                                   | `codeclone.baseline.json`            |
| `--max-baseline-size-mb MB`   | Max baseline size; untrusted baseline fails in CI, ignored otherwise | `5`                                  |
| `--update-baseline`           | Regenerate baseline from current results                             | `False`                              |
| `--fail-on-new`               | Fail if new function/block clone groups appear vs baseline           | `False`                              |
| `--fail-threshold MAX_CLONES` | Fail if total clone groups (`function + block`) exceed threshold     | `-1` (disabled)                      |
| `--ci`                        | CI preset: `--fail-on-new --no-color --quiet`                        | `False`                              |
| `--html FILE`                 | Write HTML report (`.html`)                                          | -                                    |
| `--json FILE`                 | Write JSON report (`.json`)                                          | -                                    |
| `--text FILE`                 | Write text report (`.txt`)                                           | -                                    |
| `--no-progress`               | Disable progress bar output                                          | `False`                              |
| `--no-color`                  | Disable ANSI colors                                                  | `False`                              |
| `--quiet`                     | Minimize output (warnings/errors still shown)                        | `False`                              |
| `--verbose`                   | Show hash details for new clone groups in fail output                | `False`                              |

## License

MIT License
