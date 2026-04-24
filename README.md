<div align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="https://raw.githubusercontent.com/orenlab/codeclone/main/docs/assets/codeclone-wordmark-dark.svg"
    >
    <source
      media="(prefers-color-scheme: light)"
      srcset="https://raw.githubusercontent.com/orenlab/codeclone/main/docs/assets/codeclone-wordmark.svg"
    >
    <img
      alt="CodeClone"
      src="https://raw.githubusercontent.com/orenlab/codeclone/main/docs/assets/codeclone-wordmark.svg"
      width="320"
    >
  </picture>
</div>

<p align="center">
  <strong>Structural code quality analysis for Python</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/v/codeclone.svg?style=flat-square" alt="PyPI"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/dm/codeclone.svg?style=flat-square" alt="Downloads"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/tests.yml"><img src="https://github.com/orenlab/codeclone/actions/workflows/tests.yml/badge.svg?branch=main&style=flat-square" alt="Tests"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/benchmark.yml"><img src="https://github.com/orenlab/codeclone/actions/workflows/benchmark.yml/badge.svg?style=flat-square" alt="Benchmark"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/pyversions/codeclone.svg?style=flat-square" alt="Python"></a>
  <a href="https://github.com/orenlab/codeclone"><img src="https://img.shields.io/badge/codeclone-90%20(A)-green" alt="codeclone 90 (A)"></a>
  <a href="#license"><img src="https://img.shields.io/badge/license-MPL--2.0-brightgreen?style=flat-square" alt="License"></a>
</p>

---

CodeClone provides deterministic structural code quality analysis for Python.
It detects architectural duplication, computes quality metrics, and enforces CI gates — all with **baseline-aware
governance** that separates **known** technical debt from **new** regressions.
An optional MCP interface exposes the same canonical analysis pipeline to AI agents and IDEs.

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
- **Structural findings** — duplicated branch families, clone guard/exit divergence, and clone-cohort drift
- **Quality metrics** — cyclomatic complexity, coupling (CBO), cohesion (LCOM4), dependency cycles, adaptive depth
  profile, dead code, health score, and overloaded-module profiling
- **Adoption & API** — type/docstring annotation coverage, public API surface inventory and baseline diff
- **Coverage Join** — fuse external Cobertura XML into the current run to surface coverage hotspots and scope gaps
- **Baseline governance** — separates accepted **legacy** debt from **new regressions**; CI fails only on what changed
- **Reports** — interactive HTML, JSON, Markdown, SARIF, and text from one canonical report
- **MCP server** — optional read-only surface for AI agents and IDEs
- **IDE & agent clients** — VS Code extension, Claude Desktop bundle, and Codex plugin over the same MCP contract
- **CI-first** — deterministic output, stable ordering, exit code contract, pre-commit support
- **Fast** — incremental caching, parallel processing, warm-run optimization

## Quick Start

```bash
uv tool install codeclone      # use --pre for beta

codeclone .                    # analyze
codeclone . --html             # HTML report
codeclone . --html --open-html-report  # open in browser
codeclone . --json --md --sarif --text # all formats
codeclone . --ci               # CI mode
```

<details>
<summary>More examples</summary>

```bash
# timestamped report snapshots
codeclone . --html --json --timestamped-report-paths

# changed-scope gating against git diff
codeclone . --changed-only --diff-against main

# shorthand: diff source for changed-scope review
codeclone . --paths-from-git-diff HEAD~1
```

</details>

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

<details>
<summary>What <code>--ci</code> enables</summary>
The <code>--ci</code> preset equals <code>--fail-on-new --no-color --quiet</code>.
When a trusted metrics baseline is loaded, CI mode also enables
<code>--fail-on-new-metrics</code>.
</details>

### GitHub Action

CodeClone also ships a composite GitHub Action for PR and CI workflows:

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@main
  with:
    fail-on-new: "true"
    sarif: "true"
    pr-comment: "true"
```

It can:

- run baseline-aware gating
- generate JSON and SARIF reports
- upload SARIF to GitHub Code Scanning
- post or update a PR summary comment

Action docs:
[.github/actions/codeclone/README.md](https://github.com/orenlab/codeclone/blob/main/.github/actions/codeclone/README.md)

### Quality Gates

```bash
# Metrics thresholds
codeclone . --fail-complexity 20 --fail-coupling 10 --fail-cohesion 4 --fail-health 60

# Structural policies
codeclone . --fail-cycles --fail-dead-code

# Regression detection vs baseline
codeclone . --fail-on-new-metrics

# Adoption and API governance
codeclone . --min-typing-coverage 80 --min-docstring-coverage 60
codeclone . --fail-on-typing-regression --fail-on-docstring-regression
codeclone . --api-surface --update-metrics-baseline
codeclone . --fail-on-api-break

# Coverage Join — fuse external Cobertura XML into the review
codeclone . --coverage coverage.xml --fail-on-untested-hotspots --coverage-min 50
```

Gate details:
[Metrics and quality gates](https://orenlab.github.io/codeclone/book/15-metrics-and-quality-gates/)

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

## MCP Server

Optional read-only MCP server for AI agents and IDE clients.
Never mutates source, baselines, or repo state.

```bash
uv tool install --pre "codeclone[mcp]"
# or
uv pip install --pre "codeclone[mcp]"

# local stdio clients
codeclone-mcp --transport stdio

# remote / HTTP-only clients
codeclone-mcp --transport streamable-http
```

[MCP usage guide](https://orenlab.github.io/codeclone/mcp/) ·
[MCP interface contract](https://orenlab.github.io/codeclone/book/20-mcp-interface/)

### Native Client Surfaces

| Surface                   | Location                                                                                                                     | Purpose                                            |
|---------------------------|------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------|
| **VS Code extension**     | [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone)                                 | Triage-first structural review in the editor       |
| **Claude Desktop bundle** | [`extensions/claude-desktop-codeclone/`](https://github.com/orenlab/codeclone/tree/main/extensions/claude-desktop-codeclone) | Local `.mcpb` install with pre-loaded instructions |
| **Codex plugin**          | [`plugins/codeclone/`](https://github.com/orenlab/codeclone/tree/main/plugins/codeclone)                                     | Native discovery, two skills, and MCP definition   |

All three are thin wrappers over the same `codeclone-mcp` contract — no second analysis engine.

[VS Code extension docs](https://orenlab.github.io/codeclone/book/21-vscode-extension/) ·
[Claude Desktop docs](https://orenlab.github.io/codeclone/book/22-claude-desktop-bundle/) ·
[Codex plugin docs](https://orenlab.github.io/codeclone/book/23-codex-plugin/)

## Configuration

CodeClone can load project-level configuration from `pyproject.toml`:

```toml
[tool.codeclone]
min_loc = 10
min_stmt = 6
baseline = "codeclone.baseline.json"
golden_fixture_paths = ["tests/fixtures/golden_*"]
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

Config reference:
[Config and defaults](https://orenlab.github.io/codeclone/book/04-config-and-defaults/)

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

Full policy: [Exit codes and failure policy](https://orenlab.github.io/codeclone/book/03-contracts-exit-codes/)

## Reports

| Format   | Flag      | Default path                    |
|----------|-----------|---------------------------------|
| HTML     | `--html`  | `.cache/codeclone/report.html`  |
| JSON     | `--json`  | `.cache/codeclone/report.json`  |
| Markdown | `--md`    | `.cache/codeclone/report.md`    |
| SARIF    | `--sarif` | `.cache/codeclone/report.sarif` |
| Text     | `--text`  | `.cache/codeclone/report.txt`   |

All formats are rendered from one canonical JSON report.
`--open-html-report` opens the HTML in the default browser.
`--timestamped-report-paths` appends a UTC timestamp to default filenames.

Report contract: [Report contract](https://orenlab.github.io/codeclone/book/08-report/) ·
[HTML render](https://orenlab.github.io/codeclone/book/10-html-render/)

<details>
<summary>Canonical JSON report shape (v2.9)</summary>

```json
{
  "report_schema_version": "2.9",
  "meta": {
    "codeclone_version": "2.0.0b6",
    "project_name": "...",
    "scan_root": ".",
    "report_mode": "full",
    "analysis_profile": {
      "min_loc": 10,
      "min_stmt": 6,
      "block_min_loc": 20,
      "block_min_stmt": 8,
      "segment_min_loc": 20,
      "segment_min_stmt": 10
    },
    "analysis_thresholds": {
      "design_findings": {
        "...": "..."
      }
    },
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
    "summary": {
      "...": "...",
      "coverage_adoption": {
        "...": "..."
      },
      "coverage_join": {
        "...": "..."
      },
      "api_surface": {
        "...": "..."
      }
    },
    "families": {
      "...": "...",
      "coverage_adoption": {
        "...": "..."
      },
      "coverage_join": {
        "...": "..."
      },
      "api_surface": {
        "...": "..."
      }
    }
  },
  "derived": {
    "suggestions": [],
    "overview": {
      "families": {},
      "top_risks": [],
      "source_scope_breakdown": {},
      "health_snapshot": {},
      "directory_hotspots": {}
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

Full contract: [Report contract](https://orenlab.github.io/codeclone/book/08-report/)

</details>

## Inline Suppressions

When a symbol is invoked through runtime dynamics (framework callbacks, plugin loading, reflection),
suppress the known false positive at the declaration site:

```python
# codeclone: ignore[dead-code]
def handle_exception(exc: Exception) -> None:
    ...


class Middleware:  # codeclone: ignore[dead-code]
    ...
```

Suppression contract:
[Inline suppressions](https://orenlab.github.io/codeclone/book/19-inline-suppressions/) ·
[Dead-code contract](https://orenlab.github.io/codeclone/book/16-dead-code-contract/)

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

Full docs and contract book: [orenlab.github.io/codeclone](https://orenlab.github.io/codeclone/)

Quick links:
[Baseline](https://orenlab.github.io/codeclone/book/06-baseline/) ·
[Report](https://orenlab.github.io/codeclone/book/08-report/) ·
[Metrics & gates](https://orenlab.github.io/codeclone/book/15-metrics-and-quality-gates/) ·
[MCP](https://orenlab.github.io/codeclone/book/20-mcp-interface/) ·
[CLI](https://orenlab.github.io/codeclone/book/09-cli/)

## Benchmarking Notes

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

## License

- **Code:** MPL-2.0 (`LICENSE`)
- **Documentation and docs-site content:** MIT (`LICENSE-MIT`)

Versions released before this change remain under their original license terms.

## Links

- **Docs:** <https://orenlab.github.io/codeclone/>
- **Issues:** <https://github.com/orenlab/codeclone/issues>
- **PyPI:** <https://pypi.org/project/codeclone/>
- **Licenses:** [MPL-2.0](https://github.com/orenlab/codeclone/blob/main/LICENSE) · [MIT docs](https://github.com/orenlab/codeclone/blob/main/LICENSE-MIT) · [Scope map](https://github.com/orenlab/codeclone/blob/main/LICENSES.md)
