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
      alt="CodeClone — Structural Change Controller for AI-assisted Python development"
      src="https://raw.githubusercontent.com/orenlab/codeclone/main/docs/assets/codeclone-wordmark.svg"
      width="280"
    >
  </picture>

  <p><strong>Structural Change Controller for AI-assisted Python development</strong></p>

  <p>
    <em>
      Let agents move fast.<br>
      Keep structural change explicit, bounded, remembered, and verifiable.
    </em>
  </p>

[![][pypi-shield]][pypi-link] [![][status-shield]][pypi-link] [![][downloads-shield]][pypi-link] [![][python-shield]][pypi-link] [![][license-shield]][license-link]

[![][tests-shield]][tests-link] [![][benchmark-shield]][benchmark-link]

</div>

---

> [!NOTE]
> This repository and the documentation site track the **unreleased v2.1.0 development line**.
> For the current stable release, use
> [CodeClone v2.0.2](https://github.com/orenlab/codeclone/tree/v2.0.2)
> or install [CodeClone 2.0.2 from PyPI](https://pypi.org/project/codeclone/2.0.2/).

**CodeClone** is a deterministic **Structural Change Controller** for AI-assisted Python development, built on one
canonical structural analysis of the repository.

Before editing, an agent declares intent. CodeClone maps the structural blast radius, establishes explicit edit
boundaries, and exposes the regression budget. After editing, it compares the actual patch with the declared scope,
verifies structural changes, checks review claims against report facts, and leaves an auditable receipt.

```text
intent → blast radius → bounded edit → patch check → review receipt
```

CodeClone does not use LLM judgment to classify structural regressions or authorize edits. Structural facts come
from deterministic analysis; the same facts serve agents, human reviewers, IDEs, and CI.

## Install and try

Stable release:

```bash
uv tool install codeclone
codeclone .
codeclone . --html --open-html-report
```

Run without installing:

```bash
uvx codeclone@latest .
```

Install the MCP server for local AI agents and IDE clients:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --transport stdio
```

Run the current development line from source:

```bash
git clone https://github.com/orenlab/codeclone.git
cd codeclone
uv sync --all-extras
uv run codeclone .
```

## Why CodeClone

AI coding agents accelerate implementation, but they also make scope expansion easier to miss. A narrow task can
quietly spread into shared helpers, tests, public APIs, configuration, and unrelated modules while the final diff
still looks reasonable.

Most review tools start with the completed diff. CodeClone starts with the declared intent.

```text
declare intent
  → inspect structural blast radius
  → establish edit boundaries
  → make the change
  → compare declared and actual scope
  → verify structural regressions
  → record the outcome
```

The agent still writes the code. CodeClone makes the declared scope explicit before editing and exposes undeclared
expansion when the patch is verified.

## Structural Change Controller

The controller reduces the governed agent workflow to four steps:

```text
analyze → start → edit → finish
```

- **Start controlled change** — `start_controlled_change` checks workspace state, records intent, maps blast radius,
  separates allowed paths from review context and do-not-touch boundaries, and returns the authoritative
  `edit_allowed` permission.
- **Finish controlled change** — `finish_controlled_change` resolves the actual changed files once, checks scope,
  verifies the patch against the canonical report, validates optional review claims, and produces a review receipt.
- **Patch Trail** — records declared, changed, untouched-in-declared, and boundary-held paths together with
  verification and audit anchors.
- **Multi-agent coordination** — lease-bound intents, queues, recovery, and workspace hygiene make concurrent work
  visible without treating advisory ownership as structural truth.

Host integrations can enforce the permission model before file edits where the host supports hooks. Regardless of
host enforcement, finish-time verification remains deterministic.

[Structural Change Controller documentation](https://orenlab.github.io/codeclone/book/12-structural-change-controller/)

## One canonical report, every structural surface

CodeClone runs one deterministic structural analysis and renders its canonical report through CLI, HTML, JSON,
Markdown, SARIF, MCP, IDE integrations, GitHub Action, and CI. There is no separate analysis engine for agents.

The report covers:

- function clones through CFG fingerprints;
- block clones through statement windows and report-only segment clones;
- clone-cohort drift, duplicated branch families, and guard/exit divergence;
- cyclomatic complexity, coupling, cohesion, dependency cycles, and dead code;
- overloaded-module and other report-only design context;
- type and docstring adoption;
- public API inventory and baseline-aware API break detection;
- external Cobertura coverage joined with structural hotspots;
- report-only security capability boundaries without vulnerability claims;
- deterministic structural health and review priorities.

```bash
codeclone . --json --html --md --sarif --text
```

[How CodeClone works](https://orenlab.github.io/codeclone/guide/explanation/how-it-works/) ·
[Canonical report contract](https://orenlab.github.io/codeclone/book/05-report/)

## Baseline-aware CI

CodeClone separates accepted legacy debt from new structural regressions.

```bash
# Create and commit the project baseline once
codeclone . --update-baseline

# Gate future changes against that baseline
codeclone . --ci
```

The baseline is a versioned, integrity-checked contract. CI can reject newly introduced clones and baseline-aware
metric, API, and coverage regressions without requiring the existing codebase to be clean first. Absolute threshold
gates remain opt-in.

```bash
codeclone . --fail-on-new-metrics
codeclone . --fail-complexity 20 --fail-coupling 10 --fail-cohesion 4
codeclone . --fail-cycles --fail-dead-code
codeclone . --coverage coverage.xml --fail-on-untested-hotspots
codeclone . --api-surface --fail-on-api-break
```

[Metrics and quality gates](https://orenlab.github.io/codeclone/book/16-metrics-and-quality-gates/) ·
[Baseline contract](https://orenlab.github.io/codeclone/book/07-baseline/)

## Engineering Memory

Engineering Memory gives agents durable, repository-specific context without treating model output as project truth.

The local SQLite store contains typed, evidence-linked knowledge such as contracts, architecture decisions, risks,
test anchors, public surfaces, git provenance, and prior controlled changes. Scope-aware retrieval supports the
current change, while project-wide search can combine FTS5 with optional semantic retrieval.

Audit-derived trajectories preserve how work actually unfolded. Trajectory passports, anomaly profiles, Patch Trail
evidence, and recurring advisory patterns called **Experiences** make previous successes and failures reusable.
Agent-created records remain drafts until a human approves them.

```bash
codeclone memory init --root .
codeclone memory search "baseline schema" --match all
codeclone memory approve mem-12345678
```

Memory can guide an agent. It cannot authorize edits, override blast radius, change a gate, or replace canonical
report facts.

[Engineering Memory documentation](https://orenlab.github.io/codeclone/book/13-engineering-memory/) ·
[Trajectories and Experiences](https://orenlab.github.io/codeclone/guide/memory/trajectories-and-experiences/)

## AI agents and IDE integrations

The MCP server is triage-first: analyze the repository, narrow the problem, inspect evidence, start a controlled
change, and finish with verification. `get_implementation_context` projects bounded, drift-aware structural context
for repo-relative paths from the existing run, with separate digests for the source artifact and exact response.
It is evidence for planning, never edit authorization. Bounded tools and resources keep the full report out of agent
context until deeper evidence is requested.

```bash
codeclone-mcp --transport stdio
codeclone-mcp --transport streamable-http
```

Structural analysis tools do not mutate source files, baselines, generated reports, or analysis cache. Controller
and memory operations update only their explicit state stores.

> [!WARNING]
> Analysis tools require an absolute repository root. Keep `stdio` as the default transport for local clients.
> Exposing HTTP beyond loopback requires explicit `--allow-remote`.

| Surface                   | Install or source                                                                            | Documentation                                                                                |
|---------------------------|----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| **VS Code extension**     | [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone) | [Setup](https://orenlab.github.io/codeclone/guide/integrations/vscode/setup/)                |
| **Cursor plugin**         | [Cursor storefront](https://github.com/orenlab/codeclone-cursor)                             | [Install](https://orenlab.github.io/codeclone/guide/integrations/cursor/install-and-skills/) |
| **Claude Code plugin**    | [Claude Code marketplace](https://github.com/orenlab/codeclone-claude-code)                  | [Install](https://orenlab.github.io/codeclone/guide/integrations/claude-code/setup/)         |
| **Codex plugin**          | [Codex marketplace](https://github.com/orenlab/codeclone-codex)                              | [Install](https://orenlab.github.io/codeclone/guide/integrations/codex/setup/)               |
| **Claude Desktop bundle** | [Bundle repository](https://github.com/orenlab/codeclone-claude-desktop)                     | [Setup](https://orenlab.github.io/codeclone/guide/integrations/claude-desktop/setup/)        |

Every client uses the same `codeclone-mcp` interface and canonical structural facts.

[MCP usage guide](https://orenlab.github.io/codeclone/guide/mcp/) ·
[MCP interface contract](https://orenlab.github.io/codeclone/book/25-mcp-interface/) ·
[Implementation-context tools](https://orenlab.github.io/codeclone/book/25-mcp-interface/tools/analysis/)

## Quick workflows

Review only the current Git scope:

```bash
codeclone . --changed-only --diff-against main
codeclone . --paths-from-git-diff HEAD~1
```

Inspect structural blast radius or run a baseline-relative patch check:

```bash
codeclone . --blast-radius codeclone/analysis/parser.py
codeclone . --patch-verify
```

`--patch-verify` is a terminal-only controller query: it cannot combine with
`--changed-only`, `--diff-against`, or `--paths-from-git-diff`. Use changed-scope
flags for git-selected review; use `--patch-verify` alone for a trusted-baseline
budget check on the working tree. Patch-local before/after verification with
explicit changed-file evidence belongs in MCP change control (`check_patch_contract`).

Use CodeClone in GitHub Actions:

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@v2
  with:
    fail-on-new: "true"
    sarif: "true"
    pr-comment: "true"
```

The Action can run baseline-aware gating, publish SARIF to GitHub Code Scanning, upload reports, and maintain a PR
summary comment.

[GitHub Action documentation](https://orenlab.github.io/codeclone/getting-started/#github-action)

## Platform Observability

Platform Observability is an opt-in diagnostics layer for developing CodeClone itself. It correlates CLI, MCP,
analysis, database, semantic-index, and projection-worker execution and exposes timings, RSS/CPU, query shapes,
payload pressure, causal worker chains, and costly no-ops.

It is disabled by default, stores no raw payload bodies, and cannot affect repository findings, gates, baselines,
memory facts, or edit authorization.

```bash
CODECLONE_OBSERVABILITY_ENABLED=1 codeclone .
codeclone observability trace --root . --html /tmp/codeclone-observer.html
```

[Platform Observability documentation](https://orenlab.github.io/codeclone/book/26-platform-observability/)

## Configuration

Project configuration lives in `pyproject.toml`:

```toml
[tool.codeclone]
baseline = "codeclone.baseline.json"

min_loc = 10
min_stmt = 6

block_min_loc = 20
block_min_stmt = 8
```

Precedence is **CLI flags > `pyproject.toml` > built-in defaults**.

[Configuration reference](https://orenlab.github.io/codeclone/book/10-config-and-defaults/) ·
[Inline suppressions](https://orenlab.github.io/codeclone/book/19-inline-suppressions/)

## Documentation

The documentation site contains user guides, interface contracts, report and baseline schemas, configuration
reference, integration setup, and maintainer material:

**[orenlab.github.io/codeclone](https://orenlab.github.io/codeclone/)**

## License

- **Code:** MPL-2.0 (`LICENSE`)
- **Documentation and docs-site content:** MIT (`LICENSE-MIT`)

## Links

- **Documentation:** <https://orenlab.github.io/codeclone/>
- **PyPI:** <https://pypi.org/project/codeclone/>
- **Issues:** <https://github.com/orenlab/codeclone/issues>
- **Discussions:** <https://github.com/orenlab/codeclone/discussions>
- **Licenses:** [MPL-2.0](https://github.com/orenlab/codeclone/blob/main/LICENSE) · [MIT documentation license](https://github.com/orenlab/codeclone/blob/main/LICENSE-MIT) · [License scope map](https://github.com/orenlab/codeclone/blob/main/LICENSES.md)

<!-- Shields -->
[pypi-shield]: https://img.shields.io/pypi/v/codeclone?style=flat-square&color=6366f1
[status-shield]: https://img.shields.io/pypi/status/codeclone?style=flat-square&color=6366f1
[downloads-shield]: https://img.shields.io/pypi/dm/codeclone?style=flat-square&color=6366f1
[python-shield]: https://img.shields.io/pypi/pyversions/codeclone?style=flat-square&color=6366f1
[license-shield]: https://img.shields.io/badge/license-MPL--2.0-6366f1?style=flat-square
[tests-shield]: https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/tests.yml?branch=main&style=flat-square&label=tests
[benchmark-shield]: https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/benchmark.yml?style=flat-square&label=benchmark
<!-- Links -->
[pypi-link]: https://pypi.org/project/codeclone/
[license-link]: #license
[tests-link]: https://github.com/orenlab/codeclone/actions/workflows/tests.yml
[benchmark-link]: https://github.com/orenlab/codeclone/actions/workflows/benchmark.yml
