<p align="center">
  <img src="docs/assets/codeclone-wordmark.svg" alt="CodeClone" height="60">
</p>

<p align="center">
  <strong>Structural code quality analysis for Python</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/v/codeclone.svg?style=flat-square" alt="PyPI"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/dm/codeclone.svg?style=flat-square" alt="Downloads"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/tests.yml"><img src="https://github.com/orenlab/codeclone/actions/workflows/tests.yml/badge.svg?branch=main&style=flat-square" alt="Tests"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/benchmark.yml"><img src="https://github.com/orenlab/codeclone/actions/workflows/benchmark.yml/badge.svg?style=flat-square" alt="Benchmark"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/pyversions/codeclone.svg?style=flat-square" alt="Python"></a>
  <img src="https://img.shields.io/badge/codeclone-B-green?style=flat-square" alt="CodeClone Quality">
  <a href="LICENSE"><img src="https://img.shields.io/pypi/l/codeclone.svg?style=flat-square" alt="License"></a>
</p>

---

CodeClone provides comprehensive structural code quality analysis for Python. It detects architectural
duplication via normalized AST and Control Flow Graphs, computes quality metrics, and enforces CI gates —
all with baseline-aware governance that separates **known** technical debt from **new** regressions.

## Features

- **Clone detection** — function (CFG fingerprint), block (statement windows), and segment (report-only) clones
- **Quality metrics** — cyclomatic complexity, coupling (CBO), cohesion (LCOM4), dependency cycles, dead code, health
  score
- **Baseline governance** — known debt stays accepted; CI blocks only new clones and metric regressions
- **Reports** — interactive HTML, deterministic JSON/TXT plus Markdown and SARIF projections from one canonical report
- **CI-first** — deterministic output, stable ordering, exit code contract, pre-commit support
- **Fast*** — incremental caching, parallel processing, warm-run optimization, and reproducible benchmark coverage

## Quick Start

```bash
pip install codeclone        # or: uv tool install codeclone

codeclone .                  # analyze current directory
codeclone . --html           # generate HTML report
codeclone . --json --md --sarif --text   # generate machine-readable reports
codeclone . --ci             # CI mode (--fail-on-new --no-color --quiet)
```

<details>
<summary>Run without install</summary>

```bash
uvx codeclone@latest .
```

</details>

## CI Integration

```bash
# 1. Generate baseline (commit to repo)
codeclone . --update-baseline

# 2. Add to CI pipeline
codeclone . --ci
```

The `--ci` preset equals `--fail-on-new --no-color --quiet`.
When a trusted metrics baseline is loaded, CI mode also enables
`--fail-on-new-metrics`.

### Quality Gates

```bash
# Metrics thresholds
codeclone . --fail-complexity 20 --fail-coupling 10 --fail-cohesion 4 --fail-health 60

# Structural policies
codeclone . --fail-cycles --fail-dead-code

# Regression detection vs baseline
codeclone . --fail-on-new-metrics
```

### Pre-commit

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

## Configuration

CodeClone loads project defaults from `pyproject.toml`:

```toml
[tool.codeclone]
min_loc = 20
min_stmt = 8
baseline = "codeclone.baseline.json"
skip_metrics = false
quiet = true
html_out = ".cache/codeclone/report.html"
json_out = ".cache/codeclone/report.json"
md_out = ".cache/codeclone/report.md"
sarif_out = ".cache/codeclone/report.sarif"
text_out = ".cache/codeclone/report.txt"
```

Precedence: CLI flags > `pyproject.toml` > built-in defaults.

## Baseline Workflow

Baselines capture the current duplication state. Once committed, they become the CI reference point.

- Clones are classified as **NEW** (not in baseline) or **KNOWN** (accepted debt)
- `--update-baseline` writes both clone and metrics snapshots
- Trust is verified via `generator`, `fingerprint_version`, and `payload_sha256`
- In `--ci` mode, an untrusted baseline is a contract error (exit 2)

Full contract: [`docs/book/06-baseline.md`](docs/book/06-baseline.md)

## Exit Codes

| Code | Meaning                                                                       |
|------|-------------------------------------------------------------------------------|
| `0`  | Success                                                                       |
| `2`  | Contract error — untrusted baseline, invalid config, unreadable sources in CI |
| `3`  | Gating failure — new clones or metric threshold exceeded                      |
| `5`  | Internal error                                                                |

Contract errors (`2`) take precedence over gating failures (`3`).

## Reports

| Format   | Flag      | Default path                    |
|----------|-----------|---------------------------------|
| HTML     | `--html`  | `.cache/codeclone/report.html`  |
| JSON     | `--json`  | `.cache/codeclone/report.json`  |
| Markdown | `--md`    | `.cache/codeclone/report.md`    |
| SARIF    | `--sarif` | `.cache/codeclone/report.sarif` |
| Text     | `--text`  | `.cache/codeclone/report.txt`   |

All report formats are rendered from one canonical JSON report document.

<details>
<summary>JSON report shape (v2.1)</summary>

```json
{
  "report_schema_version": "2.1",
  "meta": {
    "codeclone_version": "2.0.0b1",
    "project_name": "...",
    "scan_root": ".",
    "report_mode": "full",
    "baseline": {
      "...": "..."
    },
    "cache": {
      "...": "..."
    },
    "metrics_baseline": {
      "...": "..."
    },
    "runtime": {
      "report_generated_at_utc": "..."
    }
  },
  "inventory": {
    "files": {
      "...": "..."
    },
    "code": {
      "...": "..."
    },
    "file_registry": {
      "encoding": "relative_path",
      "items": []
    }
  },
  "findings": {
    "summary": {
      "...": "..."
    },
    "groups": {
      "clones": {
        "functions": [],
        "blocks": [],
        "segments": []
      },
      "structural": {
        "groups": []
      },
      "dead_code": {
        "groups": []
      },
      "design": {
        "groups": []
      }
    }
  },
  "metrics": {
    "summary": {},
    "families": {}
  },
  "derived": {
    "suggestions": [],
    "overview": {},
    "hotlists": {}
  },
  "integrity": {
    "canonicalization": {
      "version": "1",
      "scope": "canonical_only"
    },
    "digest": {
      "algorithm": "sha256",
      "verified": true,
      "value": "..."
    }
  }
}
```

Canonical contract: [`docs/book/08-report.md`](docs/book/08-report.md)

</details>

## How It Works

1. **Parse** — Python source to AST
2. **Normalize** — canonical structure (robust to renaming, formatting)
3. **CFG** — per-function control flow graph
4. **Fingerprint** — stable hash computation
5. **Group** — function, block, and segment clone groups
6. **Metrics** — complexity, coupling, cohesion, dependencies, dead code, health
7. **Gate** — baseline comparison, threshold checks

Architecture: [`docs/architecture.md`](docs/architecture.md) · CFG semantics: [`docs/cfg.md`](docs/cfg.md)

## Documentation

| Topic                      | Link                                                                                     |
|----------------------------|------------------------------------------------------------------------------------------|
| Contract book (start here) | [`docs/book/00-intro.md`](docs/book/00-intro.md)                                         |
| Exit codes                 | [`docs/book/03-contracts-exit-codes.md`](docs/book/03-contracts-exit-codes.md)           |
| Configuration              | [`docs/book/04-config-and-defaults.md`](docs/book/04-config-and-defaults.md)             |
| Baseline contract          | [`docs/book/06-baseline.md`](docs/book/06-baseline.md)                                   |
| Cache contract             | [`docs/book/07-cache.md`](docs/book/07-cache.md)                                         |
| Report contract            | [`docs/book/08-report.md`](docs/book/08-report.md)                                       |
| Metrics & quality gates    | [`docs/book/15-metrics-and-quality-gates.md`](docs/book/15-metrics-and-quality-gates.md) |
| Dead code                  | [`docs/book/16-dead-code-contract.md`](docs/book/16-dead-code-contract.md)               |
| Docker benchmark contract  | [`docs/book/18-benchmarking.md`](docs/book/18-benchmarking.md)                           |
| Determinism                | [`docs/book/12-determinism.md`](docs/book/12-determinism.md)                             |

## * Benchmarking

<details>
<summary>Reproducible Docker Benchmark</summary>

```bash
./benchmarks/run_docker_benchmark.sh
```

The wrapper builds `benchmarks/Dockerfile`, runs isolated container benchmarks, and writes results to
`.cache/benchmarks/codeclone-benchmark.json`.

Use environment overrides to pin the benchmark envelope:

```bash
CPUSET=0 CPUS=1.0 MEMORY=2g RUNS=16 WARMUPS=4 \
  ./benchmarks/run_docker_benchmark.sh
```

Performance claims are backed by the reproducible benchmark workflow documented
in [docs/book/18-benchmarking.md](docs/book/18-benchmarking.md)￼

</details>

## Links

- **Issues:** <https://github.com/orenlab/codeclone/issues>
- **PyPI:** <https://pypi.org/project/codeclone/>
- **License:** MIT
