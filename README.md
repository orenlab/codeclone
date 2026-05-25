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
      width="280"
    >
  </picture>

  <p><strong>Structural Change Controller for AI-assisted Python development</strong></p>

[![][pypi-shield]][pypi-link] [![][python-shield]][pypi-link] [![][downloads-shield]][pypi-link] [![][tests-shield]][tests-link] [![][license-shield]][license-link]

</div>

---

CodeClone is a **deterministic structural review layer for Python**.

It gives humans and AI coding agents one canonical view of structural code quality:
clone findings, code-health metrics, baseline-aware CI gates, coverage context,
public API changes, and a **Structural Change Controller** that starts before a
diff exists.

The controller lets agents declare intent, inspect structural blast radius,
stay inside explicit edit boundaries, verify the patch after editing, and leave
an auditable review receipt.

One canonical analysis, many surfaces: **CLI, HTML reports, JSON, SARIF, MCP,
VS Code, Claude Desktop, Codex, and CI**. Humans and agents operate on the same
deterministic facts.

Docs: [orenlab.github.io/codeclone](https://orenlab.github.io/codeclone/) &middot;
[Live report](https://orenlab.github.io/codeclone/examples/report/)

> [!NOTE]
> This README tracks the in-development **v2.1** line.
> For the latest stable release see the
> [`v2.0.2` README](https://github.com/orenlab/codeclone/blob/v2.0.2/README.md).

## Why CodeClone

AI coding agents do not just write code faster. They also expand scope faster.

A prompt asks for one change. The agent edits the target file, touches another
module because it is "related", updates a helper, changes tests, and the final
diff still looks plausible. The problem is not speed. The problem is silent
scope expansion.

CodeClone introduces a Structural Change Controller for that workflow:

```text
declare intent
→ inspect blast radius
→ constrain edit scope
→ edit
→ verify patch contract
→ validate claims
→ leave review receipt
```

CodeClone does not replace the agent and does not use LLM judgment to decide
what is safe. It gives the agent deterministic structural boundaries before the
diff exists, then verifies whether the resulting patch stayed inside them.

## Install

```bash
uv tool install codeclone          # recommended
pip install codeclone              # or pip

# with MCP server for AI agents / IDE clients
uv tool install "codeclone[mcp]"
```

<details>
<summary>Run without installing</summary>

```bash
uvx codeclone@latest .
```

</details>

## Quick Start

```bash
codeclone .                                    # analyze current directory
codeclone . --html --open-html-report          # HTML report in browser
codeclone . --ci                               # CI mode: baseline-aware gating
```

<details>
<summary>More commands</summary>

```bash
codeclone . --json --md --sarif --text          # all report formats
codeclone . --changed-only --diff-against main  # changed-scope review

# Structural Change Controller CLI surface
codeclone . --blast-radius codeclone/core/parser.py
codeclone . --patch-verify --diff-against HEAD~1
```

</details>

## Structural Change Controller

The Controller governs AI-assisted edits before they become invisible diffs.

| Stage                | Surface                                   | Purpose                                                                 |
|----------------------|-------------------------------------------|-------------------------------------------------------------------------|
| Declare intent       | `manage_change_intent`                    | Agent states intended scope before editing                              |
| Map blast radius     | `get_blast_radius` / `--blast-radius`     | Reverse imports, clone cohorts, review context, do-not-touch boundaries |
| Check patch contract | `check_patch_contract` / `--patch-verify` | Pre-edit budget and post-edit structural verification                   |
| Generate receipt     | `create_review_receipt`                   | Auditable artifact: intent, scope, blast radius, patch outcome          |
| Validate claims      | `validate_review_claims`                  | Cross-check review text against cited report facts                      |
| Coordinate workspace | workspace intent registry                 | Make active declared scopes visible across MCP processes                |

Every step is deterministic: structural facts come from the canonical report,
not from LLM inference.

Intent execution is session-local. Cross-agent visibility is optional,
advisory, TTL/lease-bound, and stored as ephemeral workspace coordination state
under `.cache/codeclone/intents/`. CodeClone never mutates source files,
baselines, generated reports, or analysis cache through MCP.

[Structural Change Controller docs](https://orenlab.github.io/codeclone/book/24-structural-change-controller/)

## What CodeClone Reviews

| Category                | What                                                                                                                           |
|-------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| **Clone structure**     | Function clones using CFG fingerprints, block clones using statement windows, segment clones as report-only review context     |
| **Structural findings** | Duplicated branch families, clone guard/exit divergence, clone-cohort drift                                                    |
| **Quality metrics**     | Cyclomatic complexity, coupling (CBO), cohesion (LCOM4), dependency cycles, adaptive dependency depth, dead code, health score |
| **Baseline governance** | Separates accepted legacy debt from new regressions so CI fails only on what got worse                                         |
| **Coverage Join**       | Fuses external Cobertura XML into the current run to surface untested hotspots and coverage scope gaps                         |
| **Adoption and API**    | Type/docstring adoption, public API surface inventory, baseline-aware API break detection                                      |
| **Security Surfaces**   | Report-only inventory of security-relevant capability boundaries without vulnerability claims                                  |
| **Design signals**      | Overloaded modules and other report-only structural review context                                                             |

## Baseline-Aware CI

```bash
# 1. Generate baseline (commit to repo)
codeclone . --update-baseline

# 2. Enforce it in CI
codeclone . --ci
```

`--ci` equals `--fail-on-new --no-color --quiet`. When a trusted metrics baseline
is present, it also enables `--fail-on-new-metrics`.

> [!TIP]
> Run `codeclone . --update-baseline` once after install. Commit the baseline
> file — it becomes the contract CI enforces on every push.

### GitHub Action

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@v2
  with:
    fail-on-new: "true"
    sarif: "true"
    pr-comment: "true"
```

Runs gating, generates reports, uploads SARIF to GitHub Code Scanning, and posts
or updates a PR summary.

[Action docs](https://github.com/orenlab/codeclone/blob/main/.github/actions/codeclone/README.md)

### Quality Gates

```bash
# Structural thresholds
codeclone . --fail-complexity 20 --fail-coupling 10 --fail-cohesion 4
codeclone . --fail-cycles --fail-dead-code --fail-health 60

# Baseline-aware metric regression detection
codeclone . --fail-on-new-metrics
codeclone . --fail-on-typing-regression --fail-on-docstring-regression

# API and coverage governance
codeclone . --api-surface --fail-on-api-break
codeclone . --coverage coverage.xml --fail-on-untested-hotspots --coverage-min 50
```

[Gate reference](https://orenlab.github.io/codeclone/book/15-metrics-and-quality-gates/)

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

## MCP Control Surface

CodeClone ships a 26-tool MCP control surface for AI agents and IDE clients.

Canonical analysis remains read-only by contract: MCP tools never mutate source
files, baselines, generated reports, or analysis cache. Controller state is
session-local or ephemeral workspace coordination state.

```bash
codeclone-mcp --transport stdio             # local clients
codeclone-mcp --transport streamable-http   # HTTP transport
```

> [!WARNING]
> Analysis tools require an absolute repository root. Relative roots like `.` are rejected.
> Keep `stdio` as the default transport for local IDE and agent clients. HTTP exposure beyond
> loopback requires explicit `--allow-remote`.

[MCP usage guide](https://orenlab.github.io/codeclone/mcp/) &middot;
[MCP interface contract](https://orenlab.github.io/codeclone/book/20-mcp-interface/)

### Native Agent and IDE Clients

| Surface            | Install                                                                                                                      | Docs                                                                        |
|--------------------|------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| **VS Code**        | [Marketplace](https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone)                                         | [Guide](https://orenlab.github.io/codeclone/book/21-vscode-extension/)      |
| **Claude Desktop** | [`extensions/claude-desktop-codeclone/`](https://github.com/orenlab/codeclone/tree/main/extensions/claude-desktop-codeclone) | [Guide](https://orenlab.github.io/codeclone/book/22-claude-desktop-bundle/) |
| **Codex**          | [`orenlab/codeclone-codex`](https://github.com/orenlab/codeclone-codex)                                                      | [Guide](https://orenlab.github.io/codeclone/book/23-codex-plugin/)          |

All clients connect to the same `codeclone-mcp` contract — no second analysis engine.

## Reports

All report formats render from one canonical JSON payload.

| Format   | Flag      | Default path                    |
|----------|-----------|---------------------------------|
| HTML     | `--html`  | `.cache/codeclone/report.html`  |
| JSON     | `--json`  | `.cache/codeclone/report.json`  |
| Markdown | `--md`    | `.cache/codeclone/report.md`    |
| SARIF    | `--sarif` | `.cache/codeclone/report.sarif` |
| Text     | `--text`  | `.cache/codeclone/report.txt`   |

```bash
codeclone . --html --json --md --sarif --text
```

[Report contract](https://orenlab.github.io/codeclone/book/08-report/) &middot;
[HTML render](https://orenlab.github.io/codeclone/book/10-html-render/)

## Configuration

CodeClone loads project-level configuration from `pyproject.toml`.

```toml
[tool.codeclone]
baseline = "codeclone.baseline.json"

min_loc = 10
min_stmt = 6

block_min_loc = 20
block_min_stmt = 8

segment_min_loc = 20
segment_min_stmt = 10

golden_fixture_paths = ["tests/fixtures/golden_*"]

html_out = ".cache/codeclone/report.html"
json_out = ".cache/codeclone/report.json"
md_out = ".cache/codeclone/report.md"
sarif_out = ".cache/codeclone/report.sarif"
text_out = ".cache/codeclone/report.txt"
```

Precedence: CLI flags > `pyproject.toml` > built-in defaults.

[Config reference](https://orenlab.github.io/codeclone/book/04-config-and-defaults/)

## Exit Codes

| Code | Meaning                                                                       |
|------|-------------------------------------------------------------------------------|
| `0`  | Success                                                                       |
| `2`  | Contract error — untrusted baseline, invalid config, unreadable sources in CI |
| `3`  | Gating failure — new clones or quality threshold exceeded                     |
| `5`  | Internal error                                                                |

Contract errors (`2`) take precedence over gating failures (`3`).

[Exit code policy](https://orenlab.github.io/codeclone/book/03-contracts-exit-codes/)

## Inline Suppressions

When a symbol is invoked through runtime dynamics — framework callbacks,
plugin loading, reflection — suppress a known false positive at the declaration
site:

```python
# codeclone: ignore[dead-code]
def handle_exception(exc: Exception) -> None:
    ...


class Middleware:  # codeclone: ignore[dead-code]
    ...
```

[Inline suppressions](https://orenlab.github.io/codeclone/book/19-inline-suppressions/) &middot;
[Dead-code contract](https://orenlab.github.io/codeclone/book/16-dead-code-contract/)

## Benchmarking

```bash
./benchmarks/run_docker_benchmark.sh
```

The Docker benchmark writes reproducible results to
`.cache/benchmarks/codeclone-benchmark.json`.

```bash
CPUSET=0 CPUS=1.0 MEMORY=2g RUNS=16 WARMUPS=4 \
  ./benchmarks/run_docker_benchmark.sh
```

[Benchmarking contract](https://orenlab.github.io/codeclone/book/18-benchmarking/)

## Documentation

Full docs and contract book: [orenlab.github.io/codeclone](https://orenlab.github.io/codeclone/)

Quick links:
[Baseline](https://orenlab.github.io/codeclone/book/06-baseline/) &middot;
[Report](https://orenlab.github.io/codeclone/book/08-report/) &middot;
[Metrics & gates](https://orenlab.github.io/codeclone/book/15-metrics-and-quality-gates/) &middot;
[MCP](https://orenlab.github.io/codeclone/book/20-mcp-interface/) &middot;
[Structural Change Controller](https://orenlab.github.io/codeclone/book/24-structural-change-controller/) &middot;
[CLI](https://orenlab.github.io/codeclone/book/09-cli/)

## License

- **Code:** MPL-2.0 (`LICENSE`)
- **Documentation and docs-site content:** MIT (`LICENSE-MIT`)

Versions released before the license change remain under their original terms.

## Links

[Docs](https://orenlab.github.io/codeclone/) &middot;
[PyPI](https://pypi.org/project/codeclone/) &middot;
[Issues](https://github.com/orenlab/codeclone/issues) &middot;
[Discussions](https://github.com/orenlab/codeclone/discussions) &middot;
[License scope map](https://github.com/orenlab/codeclone/blob/main/LICENSES.md)

<!-- Shields -->

[pypi-shield]: https://img.shields.io/pypi/v/codeclone?style=flat-square&color=6366f1

[downloads-shield]: https://img.shields.io/pypi/dm/codeclone?style=flat-square&color=6366f1

[python-shield]: https://img.shields.io/pypi/pyversions/codeclone?style=flat-square&color=6366f1

[license-shield]: https://img.shields.io/badge/license-MPL--2.0-6366f1?style=flat-square

[tests-shield]: https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/tests.yml?branch=main&style=flat-square&label=tests

<!-- Links -->

[pypi-link]: https://pypi.org/project/codeclone/

[license-link]: #license

[tests-link]: https://github.com/orenlab/codeclone/actions/workflows/tests.yml
