<p align="center">
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
</p>

<p align="center">
  <strong>Structural change controller for Python — deterministic, baseline-aware, built for CI and AI agents</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/v/codeclone?style=flat-square&color=6366f1" alt="PyPI"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/tests.yml?branch=main&style=flat-square&label=tests" alt="Tests"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/benchmark.yml"><img src="https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/benchmark.yml?style=flat-square&label=benchmark" alt="Benchmark"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/pyversions/codeclone?style=flat-square&color=6366f1" alt="Python"></a>
</p>

CodeClone is a structural change controller for Python. The v2.1 alpha starts
before the first edit — when an agent declares what it intends to change —
maps the structural blast radius, and verifies explicit before/after runs
against the patch contract. It also generates auditable review receipts; the
claim guard validates cited review claims against canonical report semantics.

The same analysis pipeline powers CLI reports, CI checks, the MCP server, and
native IDE/agent clients — so humans and AI agents operate on identical,
deterministic facts.

- Documentation: <https://orenlab.github.io/codeclone/>
- Live sample report: <https://orenlab.github.io/codeclone/examples/report/>
- Source: <https://github.com/orenlab/codeclone>
- Issues: <https://github.com/orenlab/codeclone/issues>

## Change Controller

When an AI agent edits code, CodeClone governs the structural boundary:

1. **Declare intent** — agent states what it plans to change, which files, and why
2. **Map blast radius** — reverse imports, clone cohorts, dependency cycles, do-not-touch signals
3. **Check patch contract** — pre-edit regression budget and post-edit boundary verification
4. **Generate receipt** — auditable artifact: intent + scope + patch status + structural delta
5. **Validate claims** — citation-based cross-check of review text against the canonical report

Each step is deterministic — structural facts, no LLM inference.

Docs: <https://orenlab.github.io/codeclone/book/24-structural-change-controller/>

## Features

**Change control**
- **Intent declaration** — agent states what it plans to change; CodeClone tracks scope, expiry, and status
- **Blast radius** — structural risk projection: reverse imports, clone cohorts, dependency cycles, do-not-touch signals
- **Patch contract** — pre-edit regression budget and post-edit boundary verification over explicit before/after runs
- **Review receipt** — auditable artifact linking intent, scope, patch verification, and structural delta
- **Claim guard** — citation-based validation of review text against canonical report semantics

**Baseline governance**
- **Regression isolation** — separates accepted **legacy** debt from **new regressions**; CI fails only on what changed
- **CI-first** — deterministic output, stable ordering, exit code contract, pre-commit support
- **Reports** — interactive HTML, JSON, Markdown, SARIF, and text from one canonical report

**Detection & analysis**
- **Clone detection** — function (CFG fingerprint), block (statement windows), and segment (report-only) clones
- **Structural findings** — duplicated branch families, clone guard/exit divergence, and clone-cohort drift
- **Quality metrics** — cyclomatic complexity, coupling (CBO), cohesion (LCOM4), dependency cycles, adaptive depth profile, dead code, health score, and overloaded-module profiling
- **Adoption & API** — type/docstring annotation coverage, public API surface inventory and baseline diff
- **Coverage Join** — fuse external Cobertura XML into the current run to surface coverage hotspots and scope gaps
- **Security Surfaces** — report-only inventory of security-relevant capability boundaries without vulnerability claims

**Surfaces & integrations**
- **MCP control surface** — 26-tool agent and IDE interface over the same canonical pipeline; read-only by contract
- **IDE & agent clients** — VS Code extension, Claude Desktop bundle, and Codex plugin over the same MCP contract

**Performance**
- **Fast** — incremental caching, parallel processing, warm-run optimization

## Quick Start

```bash
uv tool install codeclone

codeclone .                    # analyze
codeclone . --html             # HTML report
codeclone . --html --open-html-report
codeclone . --json --md --sarif --text
codeclone . --ci               # CI mode
```

Run without installing:

```bash
uvx codeclone@latest .
```

## CI Workflow

```bash
# 1. Generate and commit the baseline
codeclone . --update-baseline

# 2. Enforce it in CI
codeclone . --ci
```

`--ci` equals `--fail-on-new --no-color --quiet`. When a trusted metrics
baseline is loaded, CI mode also enables `--fail-on-new-metrics`.

Exit codes:

| Code | Meaning                                                                       |
|------|-------------------------------------------------------------------------------|
| `0`  | Success                                                                       |
| `2`  | Contract error — untrusted baseline, invalid config, unreadable sources in CI |
| `3`  | Gating failure — new clones or metric threshold exceeded                      |
| `5`  | Internal error                                                                |

Contract errors (`2`) take precedence over gating failures (`3`).

## Reports

```bash
codeclone . --html
codeclone . --json
codeclone . --md
codeclone . --sarif
codeclone . --text
```

All formats are rendered from one canonical report payload.

Report contract: <https://orenlab.github.io/codeclone/book/08-report/>

## MCP and Native Clients

```bash
uv tool install "codeclone[mcp]"

codeclone-mcp --transport stdio
```

The MCP server is read-only by contract: it never mutates source files,
baselines, cache, or repository state.

| Surface               | Link                                                                                 |
|-----------------------|--------------------------------------------------------------------------------------|
| VS Code extension     | <https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone>              |
| Claude Desktop bundle | <https://github.com/orenlab/codeclone/tree/main/extensions/claude-desktop-codeclone> |
| Codex plugin          | <https://github.com/orenlab/codeclone/tree/main/plugins/codeclone>                   |

MCP docs: <https://orenlab.github.io/codeclone/book/20-mcp-interface/>

## Configuration

```toml
[tool.codeclone]
baseline = "codeclone.baseline.json"
min_loc = 10
min_stmt = 6
block_min_loc = 20
block_min_stmt = 8
fail_on_new = true
fail_cycles = true
fail_dead_code = true
fail_health = 80
```

Precedence: CLI flags > `pyproject.toml` > built-in defaults.

Config reference: <https://orenlab.github.io/codeclone/book/04-config-and-defaults/>

## License

- Code: MPL-2.0 (`LICENSE`)
- Documentation and docs-site content: MIT (`LICENSE-MIT`)

License scope map: <https://github.com/orenlab/codeclone/blob/main/LICENSES.md>
