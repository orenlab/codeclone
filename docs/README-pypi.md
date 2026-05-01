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
      width="320"
    >
  </picture>
</p>

<p align="center">
  <strong>Structural code quality analysis for Python</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/v/codeclone?style=flat-square&color=6366f1" alt="PyPI"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/tests.yml?branch=main&style=flat-square&label=tests" alt="Tests"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/benchmark.yml"><img src="https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/benchmark.yml?style=flat-square&label=benchmark" alt="Benchmark"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/pyversions/codeclone?style=flat-square&color=6366f1" alt="Python"></a>
</p>

CodeClone provides deterministic structural code quality analysis for Python.
It detects architectural duplication, computes quality metrics, and enforces
CI gates with baseline-aware governance: known technical debt stays accepted,
new regressions stay visible.

The same analysis pipeline powers CLI reports, CI checks, the MCP server, and
native IDE/agent clients.

- Documentation: <https://orenlab.github.io/codeclone/>
- Live sample report: <https://orenlab.github.io/codeclone/examples/report/>
- Source: <https://github.com/orenlab/codeclone>
- Issues: <https://github.com/orenlab/codeclone/issues>

## Features

- Clone detection: function, block, and report-only segment clones.
- Structural findings: duplicated branch families, clone guard/exit divergence,
  and clone-cohort drift.
- Quality metrics: complexity, coupling, cohesion, dependency cycles, adaptive
  dependency depth, dead code, health score, and overloaded-module profiling.
- Coverage Join: combines Cobertura XML with CodeClone units to surface
  coverage hotspots and scope gaps.
- Security Surfaces: report-only inventory of security-relevant boundaries and
  sensitive capabilities. It does not claim vulnerabilities.
- Baseline governance: separates accepted legacy debt from new regressions.
- Reports: HTML, JSON, Markdown, SARIF, and text from one report payload.
- MCP control surface: read-only agent/IDE interface over the same pipeline.
- Native clients: VS Code extension, Claude Desktop bundle, and Codex plugin.

## Quick Start

```bash
uv tool install codeclone

codeclone .                    # analyze
codeclone . --html             # write HTML report
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

`--ci` enables baseline-aware gating and exits with deterministic status codes:

| Code | Meaning |
|------|---------|
| `0`  | Success |
| `2`  | Contract error, such as an untrusted baseline or invalid config |
| `3`  | Gating failure, such as new clones or failed metric thresholds |
| `5`  | Internal error |

## Reports

```bash
codeclone . --html
codeclone . --json
codeclone . --md
codeclone . --sarif
codeclone . --text
```

All report formats are rendered from the same deterministic report payload.
The HTML report is intended for human review; JSON, SARIF, Markdown, and text
are intended for automation and CI surfaces.

Report contract:
<https://orenlab.github.io/codeclone/book/08-report/>

## MCP and Native Clients

Install the optional MCP runtime when you want CodeClone in AI agents or IDEs:

```bash
uv tool install "codeclone[mcp]"

codeclone-mcp --transport stdio
```

The MCP server is read-only by contract. It does not mutate source files,
baselines, cache, or repository state.

Client surfaces:

| Surface | Link |
|---------|------|
| VS Code extension | <https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone> |
| Claude Desktop bundle | <https://github.com/orenlab/codeclone/tree/main/extensions/claude-desktop-codeclone> |
| Codex plugin | <https://github.com/orenlab/codeclone/tree/main/plugins/codeclone> |

MCP docs:
<https://orenlab.github.io/codeclone/book/20-mcp-interface/>

## Configuration

CodeClone reads project configuration from `pyproject.toml`:

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

Precedence is deterministic:

```text
CLI flags > pyproject.toml > built-in defaults
```

Config reference:
<https://orenlab.github.io/codeclone/book/04-config-and-defaults/>

## License

- Code: MPL-2.0 (`LICENSE`)
- Documentation and docs-site content: MIT (`LICENSE-MIT`)

License scope map:
<https://github.com/orenlab/codeclone/blob/main/LICENSES.md>
