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

**CodeClone** is a deterministic **structural change controller** with **Engineering Memory** for AI-assisted
Python development. It governs change *before the diff exists*: an agent declares intent, CodeClone maps the
structural blast radius, bounds the edit, verifies the resulting patch against one canonical report, and leaves an
auditable receipt. Engineering Memory adds a typed, evidence-linked project knowledge graph — contracts, decisions,
incidents, stale assumptions — so agents carry durable context without turning LLM output into truth.

It is not a linter and not LLM judgment. CodeClone makes structural **scope, context, memory, and verification**
explicit — deterministically, before the diff, and verified after. The same control surface protects human
reviewers, CI pipelines, and pre-merge gates.

## At a glance

- **Change control before the diff** — declare intent, inspect blast radius, bound the edit, verify the patch
  contract, validate review claims, leave an auditable receipt.
- **Engineering Memory** — typed, evidence-linked project facts (contracts, risks, decisions, prior changes);
  durable agent context, human-governed promotion, never LLM-as-truth.
- **One canonical report, many surfaces** — duplication, structural drift, dead code, complexity / coupling /
  cohesion, health — the same deterministic facts everywhere, no second engine.
- **Baseline-aware CI** — gates fail only on what got *worse*; accepted legacy debt stays separate from real
  regressions.
- **Built for agents and teams** — CLI · HTML · JSON · SARIF · Markdown · MCP · VS Code · Claude Desktop · Codex ·
  Cursor · GitHub Action · CI.

## Why CodeClone

AI coding agents do not just write code faster — they expand scope faster. A prompt asks for one change; the agent
edits the target file, touches another module because it looks "related", updates a helper, rewrites a few tests —
and the final diff still looks plausible. The problem is not speed. It is **silent scope expansion**.

CodeClone governs that workflow with deterministic structural boundaries:

```text
declare intent
  → inspect structural blast radius
  → constrain edit scope
  → edit
  → verify patch contract
  → validate review claims
  → leave auditable receipt
```

It does not replace the agent and does not use LLM judgment to decide what is safe. It gives the agent deterministic
boundaries **before the diff exists**, then verifies whether the resulting patch stayed inside them.

## Install

```bash
uv tool install codeclone          # recommended
pip install codeclone              # or pip

# with the MCP server for AI agents and IDE clients
uv tool install "codeclone[mcp]"

# with token-accurate MCP payload sizing (adds tiktoken)
uv tool install "codeclone[mcp,token-bench]"
```

<details>
<summary>Run without installing</summary>

```bash
uvx codeclone@latest .
```

</details>

## Quick start

```bash
codeclone .                                    # analyze the current directory
codeclone . --html --open-html-report          # interactive HTML report
codeclone . --json --md --sarif --text         # every report format
codeclone . --ci                               # CI mode: baseline-aware gating
```

<details>
<summary>More commands</summary>

```bash
# Changed-scope review against a branch
codeclone . --changed-only --diff-against main
codeclone . --paths-from-git-diff HEAD~1

# Structural Change Controller — CLI surface
codeclone . --blast-radius codeclone/analysis/parser.py
codeclone . --patch-verify --diff-against HEAD~1
```

</details>

## How it works

<details>
<summary>Pipeline overview</summary>
<br>
<img
  alt="CodeClone pipeline — parse, analyze, fuse, report, gate"
  src="docs/assets/codeclone-pipeline.svg"
  width="680"
>
</details>

CodeClone produces **one canonical JSON report** and renders it through every surface — CLI, HTML, Markdown, SARIF,
MCP, IDE extensions, GitHub Action, CI. The same deterministic facts drive human review, baseline-aware gates, and
agent workflows. The canonical report is the source of truth; surfaces render, filter, and explain it — there is
never a second analysis engine.

[Architecture narrative](https://orenlab.github.io/codeclone/guide/explanation/how-it-works/) &middot;
[CFG semantics](https://orenlab.github.io/codeclone/book/04-cfg-semantics/)

## Structural Change Controller

The Controller governs AI-assisted edits before they become invisible diffs. Every stage is deterministic —
structural facts come from the canonical report, not from LLM inference.

| Stage                        | Surface                                     | Purpose                                                                      |
|------------------------------|---------------------------------------------|------------------------------------------------------------------------------|
| **Start controlled change**  | `start_controlled_change`                   | Pre-edit: workspace check, declare scope, blast radius, patch budget         |
| **Finish controlled change** | `finish_controlled_change`                  | Post-edit: scope check, verify, optional claims/receipt, clear intent        |
| **Map blast radius**         | `get_blast_radius` · `--blast-radius`       | Reverse imports, clone cohorts, review context, do-not-touch boundaries      |
| **Check patch contract**     | `check_patch_contract` · `--patch-verify`   | Pre-edit budget check and post-edit structural verification                  |
| **Validate claims**          | `validate_review_claims`                    | Cross-check review text against the canonical report                         |
| **Generate receipt**         | `create_review_receipt`                     | Auditable artifact: intent, scope, blast radius, patch outcome               |

Intent execution is **session-local**; cross-agent visibility is optional, advisory, TTL/lease-bound, and stored as
ephemeral workspace coordination state under `.codeclone/intents/`. An optional audit trail records passive
controller events when enabled. CodeClone never mutates source files, baselines, generated reports, or analysis
cache through MCP — **read-only by contract**.

[Structural Change Controller docs](https://orenlab.github.io/codeclone/book/12-structural-change-controller/)

## What CodeClone reviews

The canonical report the Controller acts on covers:

| Category                | What it covers                                                                                                                                                  |
|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Clone detection**     | Function clones via CFG fingerprints, block clones via statement windows, segment clones as report-only review context                                          |
| **Structural findings** | Duplicated branch families, clone guard/exit divergence, clone-cohort drift                                                                                      |
| **Quality metrics**     | Cyclomatic complexity, coupling (CBO), cohesion (LCOM4), dependency cycles, adaptive depth profile, dead code, overall health score, overloaded-module profile  |
| **Baseline governance** | Separates accepted legacy debt from new regressions — CI fails only on what got worse                                                                           |
| **Coverage Join**       | Fuses external Cobertura XML into the current run to surface untested hotspots and coverage scope gaps                                                           |
| **Adoption & API**      | Type and docstring annotation coverage, public API surface inventory, baseline-aware API break detection                                                        |
| **Security Surfaces**   | Report-only inventory of security-relevant capability boundaries — no vulnerability claims                                                                       |
| **Design signals**      | Overloaded modules and other report-only structural review context                                                                                              |

## AI agents and IDE clients

CodeClone ships an MCP control surface for AI agents and IDE clients, built on the same canonical pipeline as the
CLI. Canonical analysis is **read-only by contract** — MCP tools never mutate source, baselines, reports, or cache;
controller state is session-local or ephemeral workspace coordination.

```bash
codeclone-mcp --transport stdio             # local clients (IDE, agents)
codeclone-mcp --transport streamable-http   # HTTP transport
```

Tools are triage-first (analyze → triage → drill down → focused checks → change control → session), so the full
report never floods agent context. Stable `codeclone://latest/*` and `codeclone://runs/{run_id}/*` resources return
deterministic projections, and run identity is derived from the canonical report integrity digest.

> [!WARNING]
> Analysis tools require an absolute repository root; relative roots such as `.` are rejected. Keep `stdio` as the
> default transport for local clients — HTTP exposure beyond loopback requires explicit `--allow-remote`.

[MCP usage guide](https://orenlab.github.io/codeclone/guide/mcp/) &middot;
[MCP interface contract](https://orenlab.github.io/codeclone/book/25-mcp-interface/) &middot;

### Engineering Memory

A local SQLite store of evidence-linked repository facts — contract notes, decisions, risk hotspots, git provenance,
and governed drafts. After `start_controlled_change`, agents read ranked scope context via MCP. Promotion to durable
memory is **human-governed** — agent drafts never become truth automatically. The store auto-bootstraps from the
latest MCP run (`mcp_sync_policy=bootstrap_if_missing`); `codeclone memory init` remains for CI/offline.

```bash
codeclone memory init --root .
codeclone memory search "baseline schema" --match all
codeclone memory approve mem-…   # human-only governance
```

[Engineering Memory docs](https://orenlab.github.io/codeclone/book/13-engineering-memory/)

### Native agent and IDE clients

| Surface                   | Install                                                                                                                       | Docs                                                                        |
|---------------------------|------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| **VS Code extension**     | [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=orenlab.codeclone)                                 | [Guide](https://orenlab.github.io/codeclone/guide/integrations/vscode/setup/)      |
| **Claude Desktop bundle** | [`orenlab/codeclone-claude-desktop`](https://github.com/orenlab/codeclone-claude-desktop) | [Guide](https://orenlab.github.io/codeclone/guide/integrations/claude-desktop/setup/) |
| **Codex plugin**          | [`orenlab/codeclone-codex`](https://github.com/orenlab/codeclone-codex)                                                      | [Guide](https://orenlab.github.io/codeclone/guide/integrations/codex/setup/)          |
| **Cursor plugin**         | [`orenlab/codeclone-cursor`](https://github.com/orenlab/codeclone-cursor)                       | [Guide](https://orenlab.github.io/codeclone/guide/integrations/cursor/install-and-skills/)         |

All clients connect to the same `codeclone-mcp` contract — no second analysis engine.

## CI and quality gates

```bash
# 1. Generate the baseline once, then commit it to your repo
codeclone . --update-baseline

# 2. Enforce it on every push
codeclone . --ci
```

`--ci` is equivalent to `--fail-on-new --no-color --quiet`, and enables `--fail-on-new-metrics` when a trusted
metrics baseline is present. The baseline becomes the contract CI enforces — separating accepted legacy debt from
real regressions. Exit codes: `0` success · `2` contract error · `3` gating failure · `5` internal
([policy](https://orenlab.github.io/codeclone/book/09-exit-codes/)).

<details>
<summary>Quality gate flags</summary>

```bash
# Structural metric thresholds
codeclone . --fail-complexity 20 --fail-coupling 10 --fail-cohesion 4 --fail-health 60
codeclone . --fail-cycles --fail-dead-code

# Baseline-aware regression detection
codeclone . --fail-on-new-metrics --fail-on-typing-regression --fail-on-docstring-regression

# Adoption, API, and coverage governance
codeclone . --min-typing-coverage 80 --api-surface --fail-on-api-break
codeclone . --coverage coverage.xml --fail-on-untested-hotspots --coverage-min 50
```

[Gate reference](https://orenlab.github.io/codeclone/book/16-metrics-and-quality-gates/)

</details>

### GitHub Action

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@v2
  with:
    fail-on-new: "true"
    sarif: "true"
    pr-comment: "true"
```

The Action runs baseline-aware gating, generates JSON and SARIF reports, uploads SARIF to GitHub Code Scanning, and
posts or updates a PR summary comment.
[Action docs](https://github.com/orenlab/codeclone/blob/main/.github/actions/codeclone/README.md)

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

## Reports

All formats render from one canonical JSON payload — same facts, different audiences.

| Format   | Flag      | Default path                    |
|----------|-----------|---------------------------------|
| HTML     | `--html`  | `.codeclone/report.html`  |
| JSON     | `--json`  | `.codeclone/report.json`  |
| Markdown | `--md`    | `.codeclone/report.md`    |
| SARIF    | `--sarif` | `.codeclone/report.sarif` |
| Text     | `--text`  | `.codeclone/report.txt`   |

```bash
codeclone . --html --json --md --sarif --text
```

`--open-html-report` opens the HTML in the default browser; `--timestamped-report-paths` appends a UTC timestamp to
default filenames. The canonical JSON (`report_schema_version`, `meta`, `inventory`, `findings`, `metrics`,
`derived`, `integrity`) is documented in the [report contract](https://orenlab.github.io/codeclone/book/05-report/).

## Configuration

CodeClone loads project configuration from `pyproject.toml` — precedence is
**CLI flags > `pyproject.toml` > built-in defaults**.

```toml
[tool.codeclone]
baseline = "codeclone.baseline.json"

min_loc = 10
min_stmt = 6

block_min_loc = 20
block_min_stmt = 8
```

[Config reference](https://orenlab.github.io/codeclone/book/10-config-and-defaults/) &middot;
[Inline suppressions](https://orenlab.github.io/codeclone/book/19-inline-suppressions/) &middot;
[Baseline contract](https://orenlab.github.io/codeclone/book/07-baseline/)

## Documentation

Full docs and contract book: [orenlab.github.io/codeclone](https://orenlab.github.io/codeclone/)

[Baseline](https://orenlab.github.io/codeclone/book/07-baseline/) &middot;
[Report](https://orenlab.github.io/codeclone/book/05-report/) &middot;
[Metrics & gates](https://orenlab.github.io/codeclone/book/16-metrics-and-quality-gates/) &middot;
[MCP guide](https://orenlab.github.io/codeclone/guide/mcp/) &middot;
[Structural Change Controller](https://orenlab.github.io/codeclone/book/12-structural-change-controller/) &middot;
[Engineering Memory](https://orenlab.github.io/codeclone/book/13-engineering-memory/) &middot;
[CLI](https://orenlab.github.io/codeclone/book/11-cli/) &middot;
[Benchmarking](https://orenlab.github.io/codeclone/book/20-benchmarking/)

## License

- **Code:** MPL-2.0 (`LICENSE`)
- **Documentation and docs-site content:** MIT (`LICENSE-MIT`)

## Links

- **Docs:** <https://orenlab.github.io/codeclone/>
- **PyPI:** <https://pypi.org/project/codeclone/>
- **Issues:** <https://github.com/orenlab/codeclone/issues>
- **Discussions:** <https://github.com/orenlab/codeclone/discussions>
- **Licenses:** [MPL-2.0](https://github.com/orenlab/codeclone/blob/main/LICENSE)
  &middot; [MIT docs](https://github.com/orenlab/codeclone/blob/main/LICENSE-MIT)
  &middot; [Scope map](https://github.com/orenlab/codeclone/blob/main/LICENSES.md)

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
