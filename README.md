<p align="center">
  <img src="https://orenlab.github.io/codeclone/assets/codeclone-wordmark.svg" alt="CodeClone" height="60">
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
  <a href="https://github.com/orenlab/codeclone"><img src="https://img.shields.io/badge/codeclone-81%20(B)-green" alt="codeclone 81 (B)"></a>
  <a href="https://github.com/orenlab/codeclone/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/codeclone.svg?style=flat-square" alt="License"></a>
</p>

---

CodeClone provides comprehensive structural code quality analysis for Python. It detects architectural
duplication via normalized AST and Control Flow Graphs, computes quality metrics, and enforces CI gates —
all with baseline-aware governance that separates **known** technical debt from **new** regressions.

Docs: [orenlab.github.io/codeclone](https://orenlab.github.io/codeclone/) ·
Live sample report:
[orenlab.github.io/codeclone/examples/report/](https://orenlab.github.io/codeclone/examples/report/)

> [!NOTE]
> This README and docs site track the in-development `v2.0.x` line from `main`.
> For the latest stable CodeClone documentation (`v1.4.4`), see the
> [`v1.4.4` README](https://github.com/orenlab/codeclone/blob/v1.4.4/README.md)
> and the
> [`v1.4.4` docs tree](https://github.com/orenlab/codeclone/tree/v1.4.4/docs).

## Features

- **Clone detection** — function (CFG fingerprint), block (statement windows), and segment (report-only) clones
- **Structural findings** — duplicated branch families, clone guard/exit divergence and clone-cohort drift (report-only)
- **Quality metrics** — cyclomatic complexity, coupling (CBO), cohesion (LCOM4), dependency cycles, dead code, health
  score
- **Baseline governance** — known debt stays accepted; CI blocks only new clones and metric regressions
- **Reports** — interactive HTML, deterministic JSON/TXT plus Markdown and SARIF projections from one canonical report
- **MCP server** — optional read-only MCP surface for AI agents, IDEs, and MCP-capable clients
- **CI-first** — deterministic output, stable ordering, exit code contract, pre-commit support
- **Fast*** — incremental caching, parallel processing, warm-run optimization, and reproducible benchmark coverage

## Quick Start

```bash
pip install codeclone        # or: uv tool install codeclone

codeclone .                  # analyze current directory
codeclone . --html           # generate HTML report
codeclone . --html --open-html-report   # generate and open HTML report
codeclone . --json --md --sarif --text   # generate machine-readable reports
codeclone . --html --json --timestamped-report-paths   # keep timestamped report snapshots
codeclone . --changed-only --diff-against main   # changed-scope clone gating against git diff
codeclone . --paths-from-git-diff HEAD~1         # shorthand diff source for changed-scope review
codeclone . --ci             # CI mode (--fail-on-new --no-color --quiet)
```

<details>
<summary>Run without install</summary>

```bash
uvx codeclone@latest .
```

</details>

## MCP Server

Install MCP support only when you need the agent interface:

```bash
pip install "codeclone[mcp]"
```

Then run the optional MCP launcher:

```bash
codeclone-mcp --transport stdio
# or
codeclone-mcp --transport streamable-http --port 8000
```

For local command-based clients, prefer `stdio`. Use `streamable-http` only
when the client expects a remote MCP endpoint.

CodeClone MCP is read-only and baseline-aware. It exposes deterministic tools
for:

- full repository analysis and changed-files analysis
- run summaries and run-to-run comparison
- findings, hotspots, remediation payloads, and PR summaries
- granular clone / complexity / coupling / cohesion / dead-code checks
- session-local review markers for long agent workflows

It never mutates source files, baselines, or repo state.
Diff-aware MCP calls use repo-relative `changed_paths` lists (or `git_diff_ref`)
and may reuse the same `run_id` when the canonical report digest stays
unchanged.
Focused `check_*` MCP tools may trigger a full analysis first when no stored run
exists yet.

Latest-run resources are also available for MCP-capable clients:

- `codeclone://latest/summary`
- `codeclone://latest/report.json`
- `codeclone://latest/health`
- `codeclone://latest/gates`
- `codeclone://latest/changed`
- `codeclone://schema`

Docs:
[MCP interface contract](https://orenlab.github.io/codeclone/book/20-mcp-interface/)
·
[MCP usage guide](https://orenlab.github.io/codeclone/mcp/)

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

CodeClone can load project-level configuration from `pyproject.toml`:

```toml
[tool.codeclone]
min_loc = 10
min_stmt = 6
baseline = "codeclone.baseline.json"
skip_metrics = false
quiet = false
html_out = ".cache/codeclone/report.html"
json_out = ".cache/codeclone/report.json"
md_out = ".cache/codeclone/report.md"
sarif_out = ".cache/codeclone/report.sarif"
text_out = ".cache/codeclone/report.txt"
block_min_loc = 20
block_min_stmt = 8
segment_min_loc = 20
segment_min_stmt = 10
```

Precedence: CLI flags > `pyproject.toml` > built-in defaults.

## Baseline Workflow

Baselines capture the current duplication state. Once committed, they become the CI reference point.

- Clones are classified as **NEW** (not in baseline) or **KNOWN** (accepted debt)
- `--update-baseline` writes both clone and metrics snapshots
- Trust is verified via `generator`, `fingerprint_version`, and `payload_sha256`
- In `--ci` mode, an untrusted baseline is a contract error (exit 2)

Full contract: [Baseline contract](https://orenlab.github.io/codeclone/book/06-baseline/)

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

- `--open-html-report` opens the generated HTML report in the default browser and requires `--html`.
- `--timestamped-report-paths` appends a UTC timestamp to default report filenames for bare report flags such as
  `--html` or `--json`. Explicit report paths are not rewritten.

The published docs site also includes a live example HTML/JSON/SARIF report
generated from the current `codeclone` repository during the docs build.

Structural findings include:

- `duplicated_branches`
- `clone_guard_exit_divergence`
- `clone_cohort_drift`

### Inline Suppressions

CodeClone keeps dead-code detection deterministic and static by default. When a symbol is intentionally
invoked through runtime dynamics (for example framework callbacks, plugin loading, or reflection), suppress
the known false positive explicitly at the declaration site:

```python
# codeclone: ignore[dead-code]
def handle_exception(exc: Exception) -> None:
    ...


class Middleware:  # codeclone: ignore[dead-code]
    ...
```

Dynamic/runtime false positives are resolved via explicit inline suppressions, not via broad heuristics.

<details>
<summary>JSON report shape (v2.1)</summary>

```json
{
  "report_schema_version": "2.1",
  "meta": {
    "codeclone_version": "2.0.0b3",
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
      "analysis_started_at_utc": "...",
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
    "overview": {
      "families": {},
      "top_risks": [],
      "source_scope_breakdown": {},
      "health_snapshot": {}
    },
    "hotlists": {
      "most_actionable_ids": [],
      "highest_spread_ids": [],
      "production_hotspot_ids": [],
      "test_fixture_hotspot_ids": []
    }
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

Canonical contract: [Report contract](https://orenlab.github.io/codeclone/book/08-report/) and
[Dead-code contract](https://orenlab.github.io/codeclone/book/16-dead-code-contract/)

</details>

## How It Works

1. **Parse** — Python source to AST
2. **Normalize** — canonical structure (robust to renaming, formatting)
3. **CFG** — per-function control flow graph
4. **Fingerprint** — stable hash computation
5. **Group** — function, block, and segment clone groups
6. **Metrics** — complexity, coupling, cohesion, dependencies, dead code, health
7. **Gate** — baseline comparison, threshold checks

Architecture: [Architecture narrative](https://orenlab.github.io/codeclone/architecture/) ·
CFG semantics: [CFG semantics](https://orenlab.github.io/codeclone/cfg/)

## Documentation

| Topic                      | Link                                                                                                |
|----------------------------|-----------------------------------------------------------------------------------------------------|
| Contract book (start here) | [Contracts and guarantees](https://orenlab.github.io/codeclone/book/00-intro/)                      |
| Exit codes                 | [Exit codes and failure policy](https://orenlab.github.io/codeclone/book/03-contracts-exit-codes/)  |
| Configuration              | [Config and defaults](https://orenlab.github.io/codeclone/book/04-config-and-defaults/)             |
| Baseline contract          | [Baseline contract](https://orenlab.github.io/codeclone/book/06-baseline/)                          |
| Cache contract             | [Cache contract](https://orenlab.github.io/codeclone/book/07-cache/)                                |
| Report contract            | [Report contract](https://orenlab.github.io/codeclone/book/08-report/)                              |
| Metrics & quality gates    | [Metrics and quality gates](https://orenlab.github.io/codeclone/book/15-metrics-and-quality-gates/) |
| Dead code                  | [Dead-code contract](https://orenlab.github.io/codeclone/book/16-dead-code-contract/)               |
| Docker benchmark contract  | [Benchmarking contract](https://orenlab.github.io/codeclone/book/18-benchmarking/)                  |
| Determinism                | [Determinism policy](https://orenlab.github.io/codeclone/book/12-determinism/)                      |

##  * Benchmarking

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
in [Benchmarking contract](https://orenlab.github.io/codeclone/book/18-benchmarking/)

</details>

## Links

- **Issues:** <https://github.com/orenlab/codeclone/issues>
- **PyPI:** <https://pypi.org/project/codeclone/>
- **License:** MIT
