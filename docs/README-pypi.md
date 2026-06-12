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
  <strong>Structural Change Controller for AI-assisted Python development</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/v/codeclone?style=flat-square&color=6366f1" alt="PyPI"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/pyversions/codeclone?style=flat-square&color=6366f1" alt="Python"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/tests.yml?branch=main&style=flat-square&label=tests" alt="Tests"></a>
</p>

Deterministic static analysis that combines clone detection, code-quality metrics,
and baseline-aware CI gating — structural change controller for AI-assisted
Python development.

## Quick Start

```bash
uv tool install codeclone

codeclone .                    # analyze
codeclone . --html             # HTML report
codeclone . --ci               # CI mode
```

## Key Capabilities

- **Clone detection** — function (CFG fingerprint), block, and segment clones
- **Quality metrics** — complexity, coupling, cohesion, dead code, health score
- **Baseline governance** — separates legacy debt from new regressions; CI fails only on what changed
- **Change controller** — intent declaration, blast radius, patch contract, review receipt for AI agents
- **MCP server** — 32-tool default interface for IDE and agent clients
- **Reports** — HTML, JSON, Markdown, SARIF, text from one canonical payload

## MCP Server

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --transport stdio
```

Native clients: VS Code extension, Claude Desktop bundle, Codex plugin.

## Links

- Documentation: <https://orenlab.github.io/codeclone/>
- Source: <https://github.com/orenlab/codeclone>
- Issues: <https://github.com/orenlab/codeclone/issues>

## License

- Code: MPL-2.0
- Documentation: MIT

License scope map: <https://github.com/orenlab/codeclone/blob/main/LICENSES.md>
