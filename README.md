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

  <p><strong>Structural change controller for Python</strong></p>

[![][pypi-shield]][pypi-link] [![][python-shield]][pypi-link] [![][downloads-shield]][pypi-link] [![][tests-shield]][tests-link] [![][license-shield]][license-link]

</div>

---

Deterministic static analysis that combines clone detection, code-quality metrics,
and baseline-aware CI gating — with a structural change controller for AI coding agents.

One canonical analysis, many surfaces: CLI, HTML reports, MCP server, IDE extensions.
Humans and agents operate on the same deterministic facts.

Docs: [orenlab.github.io/codeclone](https://orenlab.github.io/codeclone/) &middot;
[Live report](https://orenlab.github.io/codeclone/examples/report/)

> [!NOTE]
> This README tracks the in-development **v2.1** line.
> For the latest stable release see the
> [`v2.0.2` README](https://github.com/orenlab/codeclone/blob/v2.0.2/README.md).

## Install

```bash
uv tool install codeclone          # recommended
pip install codeclone               # or pip

# with MCP server for AI agents / IDE
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
codeclone . --ci                               # CI mode (baseline-aware gating)
```

<details>
<summary>More commands</summary>

```bash
codeclone . --json --md --sarif --text         # all report formats
codeclone . --changed-only --diff-against main # changed-scope review
codeclone . --blast-radius codeclone/core/parser.py  # structural risk map
codeclone . --patch-verify --diff-against HEAD~1     # patch verification
```

</details>

## CI Integration

```bash
# 1. Generate baseline (commit to repo)
codeclone . --update-baseline

# 2. Add to CI pipeline
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

Runs gating, generates reports, uploads SARIF to Code Scanning, posts a PR summary.
[Action docs](https://github.com/orenlab/codeclone/blob/main/.github/actions/codeclone/README.md)

### Quality Gates

```bash
codeclone . --fail-complexity 20 --fail-coupling 10 --fail-cohesion 4
codeclone . --fail-cycles --fail-dead-code --fail-health 60
codeclone . --fail-on-new-metrics --fail-on-typing-regression
codeclone . --coverage coverage.xml --fail-on-untested-hotspots
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

## What It Detects

| Category | What |
|----------|------|
| **Clones** | Function clones (CFG fingerprint), block clones (statement windows), segment clones (report-only) |
| **Structural** | Duplicated branch families, clone guard/exit divergence, clone-cohort drift |
| **Quality metrics** | Cyclomatic complexity, coupling (CBO), cohesion (LCOM4), dependency cycles, dead code, health score |
| **Adoption** | Type annotation and docstring coverage, public API surface inventory |
| **Coverage Join** | Fuses external Cobertura XML to surface coverage hotspots and scope gaps |
| **Security surfaces** | Report-only inventory of security-relevant capability boundaries |

**Baseline governance** separates accepted legacy debt from new regressions —
CI fails only on what changed. Reports render in HTML, JSON, Markdown, SARIF,
and text from one canonical JSON payload.

## Change Controller

The v2.1 structural change controller governs AI-assisted edits across five stages:

| Stage | Tool | Purpose |
|-------|------|---------|
| Declare intent | `manage_change_intent` | Agent states scope before editing |
| Map blast radius | `get_blast_radius` | Reverse imports, clone cohorts, do-not-touch |
| Check patch contract | `check_patch_contract` | Pre-edit budget / post-edit verification |
| Generate receipt | `create_review_receipt` | Auditable artifact: intent + scope + delta |
| Validate claims | `validate_review_claims` | Cross-check review text against report |

Every step is deterministic — structural facts from the canonical report, no LLM inference.
Intent is session-local; workspace coordination is ephemeral under `.cache/codeclone/intents/`.

[Change controller docs](https://orenlab.github.io/codeclone/book/24-structural-change-controller/)

## MCP Server

26-tool read-only MCP server for AI agents and IDE clients.

```bash
codeclone-mcp --transport stdio            # local clients
codeclone-mcp --transport streamable-http   # remote / HTTP clients
```

> [!WARNING]
> Analysis tools require an absolute repository root. Relative roots like `.` are rejected.

[MCP usage guide](https://orenlab.github.io/codeclone/mcp/) &middot;
[MCP interface contract](https://orenlab.github.io/codeclone/book/20-mcp-interface/)

### Native Clients

| Surface | Install | Docs |
|---------|---------|------|
| **VS Code** | [Marketplace](https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone) | [Guide](https://orenlab.github.io/codeclone/book/21-vscode-extension/) |
| **Claude Desktop** | [`extensions/claude-desktop-codeclone/`](https://github.com/orenlab/codeclone/tree/main/extensions/claude-desktop-codeclone) | [Guide](https://orenlab.github.io/codeclone/book/22-claude-desktop-bundle/) |
| **Codex** | [`plugins/codeclone/`](https://github.com/orenlab/codeclone/tree/main/plugins/codeclone) | [Guide](https://orenlab.github.io/codeclone/book/23-codex-plugin/) |

All clients connect to the same `codeclone-mcp` contract — no second analysis engine.

## Configuration

```toml
[tool.codeclone]
baseline = "codeclone.baseline.json"
min_loc = 10
min_stmt = 6
block_min_loc = 20
block_min_stmt = 8
```

Precedence: CLI flags > `pyproject.toml` > built-in defaults.
[Config reference](https://orenlab.github.io/codeclone/book/04-config-and-defaults/)

## Reports

| Format | Flag | Default path |
|--------|------|--------------|
| HTML | `--html` | `.cache/codeclone/report.html` |
| JSON | `--json` | `.cache/codeclone/report.json` |
| Markdown | `--md` | `.cache/codeclone/report.md` |
| SARIF | `--sarif` | `.cache/codeclone/report.sarif` |
| Text | `--text` | `.cache/codeclone/report.txt` |

All formats render from one canonical JSON report.
[Report contract](https://orenlab.github.io/codeclone/book/08-report/) &middot;
[HTML render](https://orenlab.github.io/codeclone/book/10-html-render/)

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `2` | Contract error — untrusted baseline, invalid config |
| `3` | Gating failure — new clones or threshold exceeded |
| `5` | Internal error |

Contract errors (`2`) take precedence over gating failures (`3`).

## License

- **Code:** MPL-2.0 (`LICENSE`)
- **Documentation:** MIT (`LICENSE-MIT`)

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
