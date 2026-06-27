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

  <p><strong>Deterministic Structural Change Controller for AI-assisted Python development</strong></p>

  <p>
    <em>
      Let agents move fast.<br>
      Keep structural change explicit, bounded, and verifiable.
    </em>
  </p>

[![][pypi-shield]][pypi-link] [![][downloads-shield]][pypi-link] [![][python-shield]][pypi-link] [![][license-shield]][license-link] [![][discord-shield]][discord-link]

[![][tests-shield]][tests-link] [![][benchmark-shield]][benchmark-link]

</div>

---

> [!NOTE]
> This README documents the unreleased **CodeClone 2.1 alpha line**.
> The basic analysis commands below work with the current stable release,
> [CodeClone 2.0.2](https://github.com/orenlab/codeclone/tree/v2.0.2).
> Agent change control and Engineering Memory require the 2.1 prerelease.

## What is CodeClone?

CodeClone helps developers use AI coding agents without losing control of structural change.

Before an agent edits code, CodeClone records the intended change, maps the structural blast radius, and establishes
explicit edit boundaries. After the edit, it compares the real patch with the declared scope, verifies structural
regressions, and leaves an auditable review receipt.

CodeClone makes silent scope expansion visible before it disappears inside an otherwise reasonable-looking diff.

CodeClone does not ask an LLM to decide whether a structural change is safe. It uses deterministic repository facts
shared across agents, human reviewers, IDEs, reports, and CI.

## Quick start

### 1. Analyze a repository

Run the stable release without installing anything:

```bash
uvx codeclone@latest .
```

Prefer a browsable report? Generate the HTML view and open it:

```bash
uvx codeclone@latest . --html --open-html-report
```

Once you use it regularly, install it as a local tool:

```bash
uv tool install codeclone
codeclone .
```

### 2. Record the current structural baseline

Before asking an agent to change the repository, capture the accepted state once:

```bash
codeclone . --update-baseline
git add codeclone.baseline.json
git commit -m "chore: add CodeClone structural baseline"
```

The baseline records the structural debt that already exists. Future analysis can then separate **new regressions**
from findings that were already present, so agents and reviewers can focus on what the current change introduced.

Updating the baseline is an explicit governance action. Do not regenerate it merely to make a failing check pass.

### 3. Set up CodeClone for your AI agent (2.1 alpha)

Install the prerelease MCP server:

```bash
uv tool install --prerelease allow "codeclone[mcp]"
codeclone-mcp --transport stdio
```

Then wire it into your client:

| Client         | Setup                                                                                                  |
|----------------|--------------------------------------------------------------------------------------------------------|
| VS Code        | [Extension setup](https://orenlab.github.io/codeclone/guide/integrations/vscode/setup/)                |
| Cursor         | [Plugin and skills](https://orenlab.github.io/codeclone/guide/integrations/cursor/install-and-skills/) |
| Claude Code    | [Plugin setup](https://orenlab.github.io/codeclone/guide/integrations/claude-code/setup/)              |
| Codex          | [Plugin setup](https://orenlab.github.io/codeclone/guide/integrations/codex/setup/)                    |
| Claude Desktop | [Bundle setup](https://orenlab.github.io/codeclone/guide/integrations/claude-desktop/setup/)           |

Every client uses the same MCP interface and the same canonical structural facts.

## How the controlled-change workflow works

For an agent, the normal workflow is:

```text
analyze → start → edit → finish
```

### Analyze

CodeClone builds one canonical structural report for the repository and compares it with the accepted baseline.

### Start

`start_controlled_change`:

- records the agent's intent;
- maps structural blast radius;
- separates editable paths from review context and do-not-touch boundaries;
- exposes the regression budget relative to the accepted baseline;
- returns the authoritative `edit_allowed` result.

### Edit

The agent writes the code. CodeClone does not generate or rewrite source files.

Where the host supports hooks, integrations can stop edits unless `edit_allowed=true`.

### Finish

`finish_controlled_change`:

- resolves the actual changed files;
- checks declared scope against the real patch;
- verifies structural changes;
- validates optional review claims;
- records Patch Trail evidence;
- produces an auditable review receipt.

The result is not an AI opinion about the patch. It is a deterministic comparison between declared intent, repository
structure, the accepted baseline, and the actual change.

[Read the Structural Change Controller guide](https://orenlab.github.io/codeclone/book/12-structural-change-controller/)

## What you get

| Capability                        | What it provides                                                                                                                    |
|-----------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| **Structural Change Controller**  | Intent-first change control, blast radius, explicit edit boundaries, patch verification, and review receipts                        |
| **Canonical structural analysis** | Clone detection, complexity, coupling, cohesion, dependency cycles, dead code, API inventory, coverage joins, and structural health |
| **Baseline-aware governance**     | Records accepted legacy debt and separates it from regressions introduced by the current change                                     |
| **Engineering Memory**            | Local, typed, evidence-linked project knowledge and reusable histories of prior controlled changes                                  |
| **Agent coordination**            | Lease-bound intents, queues, conflicts, recovery, and workspace hygiene                                                             |
| **One report, many surfaces**     | CLI, HTML, JSON, Markdown, SARIF, MCP, IDE integrations, and GitHub Actions from one canonical payload                              |

CodeClone requires no hosted service or cloud account. Analysis state, controller state, Engineering Memory, and
trajectories are stored locally.

## Why intent comes before the diff

Most review tools begin after the patch already exists. CodeClone begins earlier:

```text
task request
  → declared intent
  → structural blast radius
  → explicit boundary
  → actual patch
  → deterministic verification
```

Agent scope expansion can look reasonable in the final diff. A narrow task may quietly spread into shared helpers,
tests, configuration, public APIs, or unrelated modules.

By the time that expansion reaches the final diff, it already looks intentional. CodeClone catches it at the declared
boundary instead — by comparing what the agent said it would change with what it actually changed.

## One canonical structural report

CodeClone runs one deterministic analysis and renders the same canonical report through every supported surface.

The report covers:

- function, block, and segment clones;
- clone drift and duplicated branch families;
- complexity, coupling, cohesion, dependency cycles, and dead code;
- public API inventory and baseline-aware API break detection;
- external coverage joined with structural hotspots;
- deterministic structural health and review priorities.

```bash
codeclone . --json --html --md --sarif --text
```

[How CodeClone works](https://orenlab.github.io/codeclone/guide/explanation/how-it-works/) ·
[Canonical report contract](https://orenlab.github.io/codeclone/book/05-report/)

## Baseline-aware governance and CI

The baseline is a versioned, integrity-checked contract that records the accepted structural state of the repository.

It lets CodeClone and connected agents distinguish:

- findings that already existed;
- regressions introduced by the current change;
- deliberate baseline updates approved by the user.

Check future changes against the committed baseline:

```bash
codeclone . --ci
```

Use CodeClone in GitHub Actions:

```yaml
- uses: orenlab/codeclone/.github/actions/codeclone@v2
  with:
    fail-on-new: "true"
    sarif: "true"
    pr-comment: "true"
```

CI can reject newly introduced clones, metric regressions, API breaks, and coverage regressions without requiring the
existing repository to be clean first.

[Baseline contract](https://orenlab.github.io/codeclone/book/07-baseline/) ·
[Metrics and quality gates](https://orenlab.github.io/codeclone/book/16-metrics-and-quality-gates/) ·
[GitHub Action documentation](https://orenlab.github.io/codeclone/getting-started/#github-action)

## Engineering Memory

Engineering Memory gives agents durable, repository-specific context without treating model output as project truth.

The local SQLite store can contain:

- architecture and contract notes;
- risks, test anchors, and public surfaces;
- git and change-control provenance;
- prior trajectories and Patch Trail evidence;
- recurring advisory patterns called **Experiences**.

Agent-created records remain drafts until a human approves them.

```bash
codeclone memory init --root .
codeclone memory search "baseline schema" --match all
```

Memory can guide an agent. It cannot authorize edits, override blast radius, change a gate, or replace canonical report
facts.

[Engineering Memory documentation](https://orenlab.github.io/codeclone/book/13-engineering-memory/) ·
[Trajectories and Experiences](https://orenlab.github.io/codeclone/guide/memory/trajectories-and-experiences/)

## Trust boundaries

- Structural findings and gates come from deterministic analysis, not LLM judgment.
- `edit_allowed` is an explicit controller result; status or advisory ownership does not grant permission.
- Read-only analysis commands do not modify source code or project governance state.
- Baseline updates are explicit user-approved governance actions.
- Controller and memory operations write only to their explicit local state stores.
- Memory and trajectory evidence remain advisory.
- `stdio` is the recommended transport for local clients.
- Remote HTTP exposure requires explicit `--allow-remote`.

## Development setup

Run the repository version from source:

```bash
git clone https://github.com/orenlab/codeclone.git
cd codeclone
uv sync --all-extras
uv run codeclone .
```

CodeClone 2.1 requires Python 3.10 or newer.

## Documentation

**[orenlab.github.io/codeclone](https://orenlab.github.io/codeclone/)**

- [Getting started](https://orenlab.github.io/codeclone/getting-started/)
- [Structural Change Controller](https://orenlab.github.io/codeclone/book/12-structural-change-controller/)
- [Engineering Memory](https://orenlab.github.io/codeclone/book/13-engineering-memory/)
- [MCP usage](https://orenlab.github.io/codeclone/guide/mcp/)
- [Configuration reference](https://orenlab.github.io/codeclone/book/10-config-and-defaults/)

## License

- **Code:** MPL-2.0
- **Documentation:** MIT

See [LICENSES.md](https://github.com/orenlab/codeclone/blob/main/LICENSES.md) for the license scope map.

## Links

- **PyPI:** <https://pypi.org/project/codeclone/>
- **Discord:** <https://discord.com/invite/U72KmRvpUx>
- **Issues:** <https://github.com/orenlab/codeclone/issues>
- **Discussions:** <https://github.com/orenlab/codeclone/discussions>

<!-- Shields -->
[pypi-shield]: https://img.shields.io/pypi/v/codeclone?style=flat-square&color=6366f1
[downloads-shield]: https://img.shields.io/pypi/dm/codeclone?style=flat-square&color=6366f1
[python-shield]: https://img.shields.io/pypi/pyversions/codeclone?style=flat-square&color=6366f1
[license-shield]: https://img.shields.io/badge/license-MPL--2.0-6366f1?style=flat-square
[tests-shield]: https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/tests.yml?branch=main&style=flat-square&label=tests
[benchmark-shield]: https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/benchmark.yml?branch=main&style=flat-square&label=benchmark
[discord-shield]: https://img.shields.io/badge/Discord-Join%20community-5865F2?style=flat-square&logo=discord&logoColor=white

<!-- Links -->
[pypi-link]: https://pypi.org/project/codeclone/
[license-link]: #license
[tests-link]: https://github.com/orenlab/codeclone/actions/workflows/tests.yml
[benchmark-link]: https://github.com/orenlab/codeclone/actions/workflows/benchmark.yml
[discord-link]: https://discord.com/invite/U72KmRvpUx
