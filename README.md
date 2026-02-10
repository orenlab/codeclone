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

- discover structural and control-flow duplication
- identify architectural hotspots early
- prevent new duplication via CI and pre-commit hooks

## Why CodeClone

CodeClone focuses on **architectural duplication**, not text similarity.
It is robust to renaming, formatting, and minor refactors while preserving strict, explainable matching.
Unlike token-based tools, it compares normalized structure and control flow.

Typical signals:

- repeated service/orchestration flow
- duplicated guard/validation blocks
- copy-pasted handler logic across modules
- recurring internal segments in large functions

## Core Capabilities

- **Function clones (CFG fingerprint):** strong structural signal for cross-layer duplication.
- **Block clones (statement windows):** detects repeated local logic patterns.
- **Segment clones (report-only):** internal function repetition for explainability; not used for baseline gating.
- **Deterministic output:** stable ordering and reproducible artifacts for CI/audit.

## Installation

```bash
pip install codeclone
```

Python 3.10+ is required.

## Quick Start

Run analysis:

```bash
codeclone .
```

Generate reports:

```bash
codeclone . \
  --html .cache/codeclone/report.html \
  --json .cache/codeclone/report.json \
  --text .cache/codeclone/report.txt
```

Print version:

```bash
codeclone --version
```

## Baseline and CI Workflow

1. Generate baseline once and commit it:

```bash
codeclone . --update-baseline
```

2. Gate CI with the preset mode:

```bash
codeclone . --ci
```

`--ci` is equivalent to `--fail-on-new --no-color --quiet`.

### Baseline Contract (v1)

Baseline compatibility is tied to `fingerprint_version` (not package patch/minor version).
Regenerate baseline only when `fingerprint_version` changes.

Canonical structure:

```json
{
  "meta": {
    "generator": {
      "name": "codeclone",
      "version": "1.4.0"
    },
    "schema_version": "1.0",
    "fingerprint_version": "1",
    "python_tag": "cp313",
    "created_at": "2026-02-09T11:44:08Z",
    "payload_sha256": "..."
  },
  "clones": {
    "functions": [],
    "blocks": []
  }
}
```

### Trusted vs Untrusted Baseline

Untrusted statuses:

- `missing`
- `too_large`
- `invalid_json`
- `invalid_type`
- `missing_fields`
- `mismatch_schema_version`
- `mismatch_fingerprint_version`
- `mismatch_python_version`
- `generator_mismatch`
- `integrity_missing`
- `integrity_failed`

Behavior:

- **Normal mode:** warn, ignore baseline, compare against empty baseline.
- **Gating mode (`--ci`):** fail fast with exit code `2` if baseline is untrusted.
- **Gating mode with trusted baseline:** new clones / threshold violations return exit code `3`.

Legacy baseline layouts (`<= 1.3.x`) are treated as untrusted.

## Reports

Supported formats:

- HTML (`--html`)
- JSON (`--json`)
- Text (`--text`)

All report formats include provenance metadata, including baseline trust fields and cache usage fields when available.

Primary metadata keys:

- `codeclone_version`
- `python_version`
- `baseline_path`
- `baseline_fingerprint_version`
- `baseline_schema_version`
- `baseline_python_tag`
- `baseline_generator_version`
- `baseline_loaded`
- `baseline_status`
- `cache_path` / `cache_used` (when present)

## Cache

Default cache location:

```text
<root>/.cache/codeclone/cache.json
```

- Override with `--cache-path` (`--cache-dir` is a legacy alias).
- Invalid/oversized cache is ignored with warning and rebuilt from source.
- Cache is an optimization only; never a source of truth.

If you upgraded from older versions, remove legacy cache at:

```text
~/.cache/codeclone/cache.json
```

and add `.cache/` to `.gitignore`.

## Exit Codes

- `0` success
- `2` contract error (baseline untrusted in gating, invalid output extension, incompatible versions)
- `3` gating failure (new clones detected, threshold exceeded)
- `5` internal error (unexpected exception)

## Project Links

- Repository: https://github.com/orenlab/codeclone
- Issues: https://github.com/orenlab/codeclone/issues
- Docs: https://github.com/orenlab/codeclone/tree/main/docs

## Pre-commit Example

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

## What CodeClone Is (and Is Not)

### CodeClone Is

- a structural clone detector for Python
- a CI guard against new duplication
- a deterministic analysis tool with auditable outputs

### CodeClone Is Not

- a linter or formatter
- a semantic equivalence prover
- a runtime execution analyzer

## High-level Pipeline

1. Parse Python source to AST.
2. Normalize AST for structural comparison.
3. Build CFG per function.
4. Compute stable fingerprints.
5. Build function/block/segment groups.
6. Apply deterministic report preparation.
7. Compare against trusted baseline when requested.

See details:

- [docs/architecture.md](docs/architecture.md)
- [docs/cfg.md](docs/cfg.md)

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
| `--fail-on-new`               | Low-level gating flag (prefer `--ci`)                                | `False`                              |
| `--fail-threshold MAX_CLONES` | Fail if total clone groups (`function + block`) exceed threshold     | `-1` (disabled)                      |
| `--ci`                        | Recommended CI preset: `--fail-on-new --no-color --quiet`            | `False`                              |
| `--html FILE`                 | Write HTML report (`.html`)                                          | -                                    |
| `--json FILE`                 | Write JSON report (`.json`)                                          | -                                    |
| `--text FILE`                 | Write text report (`.txt`)                                           | -                                    |
| `--no-progress`               | Disable progress bar output                                          | `False`                              |
| `--no-color`                  | Disable ANSI colors                                                  | `False`                              |
| `--quiet`                     | Minimize output (warnings/errors still shown)                        | `False`                              |
| `--verbose`                   | Show hash details for new clone groups in fail output                | `False`                              |

## License

MIT License
