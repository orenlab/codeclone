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
  <strong>Deterministic Structural Change Controller for AI-assisted Python development</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/v/codeclone?style=flat-square&color=6366f1" alt="PyPI"></a>
  <a href="https://pypi.org/project/codeclone/"><img src="https://img.shields.io/pypi/pyversions/codeclone?style=flat-square&color=6366f1" alt="Python"></a>
  <a href="https://github.com/orenlab/codeclone/actions/workflows/tests.yml"><img src="https://img.shields.io/github/actions/workflow/status/orenlab/codeclone/tests.yml?branch=main&style=flat-square&label=tests" alt="Tests"></a>
</p>

CodeClone helps developers use AI coding agents without losing control of structural change. Before an agent edits
code, it records the intended change, maps the structural blast radius, and establishes explicit edit boundaries. After
the edit, it compares the real patch with the declared scope, verifies structural regressions, and leaves an auditable
review receipt.

Every finding and every gate comes from deterministic repository facts — not an LLM opinion — shared across agents,
human reviewers, IDEs, reports, and CI. CodeClone does not generate or rewrite source files.

> **Note:** Features marked `2.1 alpha` require the
> [CodeClone 2.1 prerelease](https://pypi.org/project/codeclone/#history). Everything else works with the current
> stable release.

## Quick start

Requires Python 3.10 or newer.

```bash
uvx codeclone@latest .              # analyze without installing
uvx codeclone@latest . --html --open-html-report

uv tool install codeclone           # install as a local tool
codeclone .
```

Record the accepted structural baseline once, then gate future changes against it in CI:

```bash
codeclone . --update-baseline
codeclone . --ci
```

The baseline separates **new regressions** from findings that already existed, so CI fails only on what the current
change introduced.

## What it provides

- **Structural Change Controller** — `2.1 alpha`: intent-first change control, blast radius, explicit edit boundaries,
  patch verification, and review receipts.
- **Baseline-aware governance** — records accepted legacy debt and separates it from regressions introduced by the
  current change.
- **One canonical report** — clones, complexity, coupling, cohesion, dead code, dependency cycles, a package/module
  dependency map (Module Map), public API inventory, coverage joins, and a guided finding-review queue, rendered
  through CLI, HTML, JSON, Markdown, SARIF, and CI from one payload.
- **Engineering Memory** — `2.1 alpha`: local, typed, evidence-linked project knowledge and reusable histories of prior
  controlled changes.
- **Agent coordination** — `2.1 alpha`: conflict-safe multi-agent intents, queues, recovery, and workspace hygiene.

CodeClone requires no hosted service or cloud account. Analysis state, controller state, Engineering Memory, and
trajectories are stored locally.

## MCP control surface and native clients

```bash
uv tool install --prerelease allow "codeclone[mcp]"
codeclone-mcp --transport stdio
```

The MCP server is contained by contract: it writes only CodeClone's own service data, and only inside CodeClone's
service directories (`.codeclone/` and the per-user cache directory). Source files, baselines and generated reports are
never mutated. The same canonical structural facts back every client — VS Code, Cursor, Claude Code, Codex, and Claude
Desktop.

## Links

- Documentation: <https://orenlab.github.io/codeclone/>
- Getting started: <https://orenlab.github.io/codeclone/getting-started/>
- Structural Change Controller: <https://orenlab.github.io/codeclone/concepts/controlled-change/>
- Engineering Memory: <https://orenlab.github.io/codeclone/concepts/engineering-memory/>
- Configuration reference: <https://orenlab.github.io/codeclone/reference/configuration/>
- Source: <https://github.com/orenlab/codeclone>
- Issues: <https://github.com/orenlab/codeclone/issues>

## License

- Code: MPL-2.0
- Documentation: MIT

See [LICENSES.md](https://github.com/orenlab/codeclone/blob/main/LICENSES.md) for the license scope map.
