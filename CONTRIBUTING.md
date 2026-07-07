# Contributing to CodeClone

Thank you for contributing to **CodeClone**.

**CodeClone** is a deterministic **Structural Change Controller** for
AI-assisted Python development.

It starts before a diff exists: an agent declares intent, CodeClone maps the
structural blast radius, bounds the edit, verifies the resulting patch against
one canonical report, and leaves an auditable receipt.

```text
intent → blast radius → bounded edit → patch check → review receipt
```

CodeClone combines structural analysis, baseline-aware CI, Engineering Memory,
agent trajectories, MCP tooling, and IDE integrations without turning LLM
output into truth. It is not an AI reviewer guessing whether code is safe; it
is a deterministic control layer for structural change.

Contributions are welcome when they preserve the project's central guarantees:
honesty, reproducibility, determinism, explainability, and safe use in real
CI environments.

## Source of Truth

Before changing code, read:

- [`AGENTS.md`](AGENTS.md) for repository-wide operating rules, module
  ownership, change routing, and required validation;
- the [architecture map](docs/book/02-architecture-map.md) for current
  boundaries and dependency direction;
- [testing as specification](docs/book/23-testing-as-spec.md) for contract and
  test ownership;
- the relevant contract chapter under [`docs/book/`](docs/book/).

The current repository code is the source of truth for implementation
behavior. Version constants must be read from
`codeclone/contracts/__init__.py`, not copied from this file or another
document. If contributor documentation and code diverge, align the
documentation as part of the change.

## Project Principles

- **Determinism over cleverness.** Identical inputs and versions must produce
  stable findings, ordering, identities, and canonical payloads.
- **Control starts before the diff.** Intent, scope, blast radius, and
  do-not-touch boundaries are part of the change contract, not review
  commentary added afterward.
- **Evidence over inference.** Core analysis produces facts and metrics;
  renderers and clients present them without inventing new gating semantics.
- **Low noise over inflated recall.** Detection changes must account for both
  false positives and false negatives.
- **One analysis truth.** CLI, reports, MCP, extensions, and plugins project the
  same canonical pipeline and report contracts.
- **Contracts are public APIs.** Baselines, cache compatibility, report
  schemas, CLI behavior, MCP payloads, and published integration behavior
  require deliberate compatibility handling.
- **Safety first.** Treat source code, paths, configuration, baselines, caches,
  and external tool input as untrusted.

Changes that increase unexplained noise, introduce nondeterminism, weaken
contract boundaries, or silently change trusted artifacts are unlikely to be
accepted.

## AI-Assisted Contributions

CodeClone accepts contributions written with coding agents, language models,
and other automated development tools. Agent assistance is welcome, including
substantial agent-authored code, but it does not transfer responsibility away
from people.

Every AI-assisted contribution must meet all of the following requirements:

- A human contributor must inspect the complete diff, understand it, and be
  able to explain and maintain it.
- A human must verify the relevant tests, contract implications, security
  properties, generated artifacts, and documentation before requesting review.
- A substantive human review is mandatory before merge. Agent-only review,
  automated approval, or a passing CI run does not satisfy this requirement.
- Material agent assistance should be disclosed in the pull request
  description, including what the agent produced or changed.
- The contributor must verify provenance, licensing, and third-party rights for
  generated code, text, fixtures, and assets.
- Secrets, private prompts, credentials, unrelated user data, and unreviewed
  generated output must not be committed.
- Do not submit code that no human can confidently explain, test, or support.

CodeClone's Structural Change Controller, Engineering Memory, review receipts,
claim validation, and Platform Observability can strengthen review evidence.
They do not replace human engineering judgment or human approval.

## Where to Contribute

Contributions are especially useful in:

- Structural Change Controller intent, scope, blast-radius, patch-contract,
  claim-validation, and receipt workflows;
- Engineering Memory retrieval, semantic indexing, trajectories, Patch Trail,
  Experiences, governance, and projection jobs;
- Platform Observability instrumentation and developer diagnostics;
- AST normalization, CFG construction, and structural extraction;
- clone grouping, explainability, and false-positive reduction;
- complexity, coupling, cohesion, dependency, dead-code, coverage, adoption,
  API-surface, and health metrics;
- baseline, cache, canonical report, and deterministic renderer contracts;
- MCP tools, resources, messages, and transport behavior;
- VS Code, Claude Desktop, Claude Code, Codex, Cursor, and GitHub Action surfaces;
- performance work that preserves fingerprint and canonical-output semantics;
- documentation, examples, tests, and real-world CI scenarios.

Use the module ownership table in [`AGENTS.md`](AGENTS.md) and the
[architecture map](docs/book/02-architecture-map.md) to route changes to the
correct layer.

## Contribution Workflow

1. Confirm the user-visible problem and identify the owning module.
2. Classify whether the change affects a versioned or public contract.
3. Read the nearest tests and normative documentation before editing.
4. Keep the patch narrowly scoped and preserve unrelated work in the tree.
5. Add tests in the test module that owns the behavior. Do not create generic
   coverage-uplift or miscellaneous test dumping grounds.
6. Update documentation when behavior, configuration, commands, payloads, or
   public integration surfaces change.
7. Run the relevant focused checks, then the repository validation required
   below.
8. Review the final diff as a human-readable change, not merely as passing
   automation.

When CodeClone MCP change control is available, contributors and coding agents
should use `start_controlled_change` before editing and
`finish_controlled_change` after verification. These tools bind intent, scope,
blast radius, patch budget, verification, and the review receipt. The atomic
tools remain available for deeper inspection and recovery. See the
[Structural Change Controller](docs/book/12-structural-change-controller/index.md).

## Reporting Bugs

Use the appropriate GitHub issue template. Include:

- a minimal reproducer, preferably source text rather than screenshots;
- CodeClone and Python versions;
- the command, configuration, and relevant optional extras;
- expected and actual behavior;
- whether a baseline, cache, coverage XML, MCP client, memory store, semantic
  sidecar, projection worker, or observability store was involved;
- sanitized logs or payload excerpts where useful.

Classify the affected area when possible: change control/blast radius,
Engineering Memory/trajectories, analysis/CFG, normalization, clones, metrics,
baseline/cache/report, CLI, MCP, observability, documentation, or a
client/integration surface.

For false positives, explain why the detected code is architecturally distinct
in control flow, responsibilities, or structure. Naming, comments, and
formatting alone are not sufficient evidence.

For a suspected Platform Observability issue, include the operation or
correlation ID and a bounded, sanitized JSON projection when possible. Never
attach raw repository secrets or private source unnecessarily.

## Design-Sensitive Changes

### Analysis, CFG, and fingerprints

For AST normalization, CFG, extraction, or clone identity changes, describe:

- current and proposed behavior;
- concrete positive and negative examples;
- expected false-positive and false-negative impact;
- determinism implications;
- baseline and fingerprint compatibility implications.

Performance work must not change normalization, fingerprint inputs, clone
identity, or NEW-versus-KNOWN classification while
`BASELINE_FINGERPRINT_VERSION` is unchanged. Fingerprint-adjacent changes
require explicit maintainer approval, version review, migration/release notes,
tests, and documentation.

### Golden tests

Golden tests are contract sentinels. Do not update snapshots merely to make a
failure disappear. A golden update is acceptable only when the contract change
is intentional, reviewed, documented, and versioned where required.

### Security and safety

- Preserve path validation and repository-root containment.
- Keep normal-mode fail-open and gating-mode fail-closed behavior only where
  the owning contract explicitly defines it.
- Add negative tests for parser, normalization, transport, path, and
  persistence boundaries.
- Do not let UI, MCP, memory, observability, or client surfaces invent analysis
  facts or authorization.

See the [security model](docs/book/21-security-model.md).

## Versioned Contracts

Current values must always be verified in `codeclone/contracts/__init__.py`.
At the time this document was updated, the main contracts were:

| Contract               | Version | Primary owner                     |
|------------------------|--------:|-----------------------------------|
| Baseline schema        |   `2.1` | `codeclone/baseline/`             |
| Baseline fingerprint   |     `1` | `codeclone/contracts/__init__.py` |
| Analysis cache         |  `2.10` | `codeclone/cache/`                |
| Canonical report       |  `2.12` | `codeclone/report/document/`      |
| Metrics baseline       |   `1.2` | `codeclone/baseline/`             |
| Engineering Memory     |   `1.7` | `codeclone/memory/`               |
| Semantic index format  |     `3` | `codeclone/memory/semantic/`      |
| Platform Observability |   `1.1` | `codeclone/observability/`        |

Any schema shape or semantic change requires version review, tests, and
documentation. Compatibility details live in
[compatibility and versioning](docs/book/24-compatibility-and-versioning.md).

### Baseline and CI behavior

- Baseline trust depends on schema compatibility, fingerprint version, Python
  tag, generator identity, and canonical payload integrity.
- Regenerate the baseline when fingerprint compatibility or Python tag changes.
- Do not regenerate it for report-only, UI-only, cache-only, or performance-only
  work that preserves fingerprint semantics.
- Untrusted baseline state fails fast with exit `2` in gating mode.
- Outside gating mode, an untrusted baseline is ignored with a warning and
  comparison proceeds against an empty baseline.
- Baseline novelty is baseline-relative. Patch-local regression claims require
  a clean before/after comparison.

Public exit categories are:

- `0`: success;
- `2`: contract or invocation error;
- `3`: analysis/quality gate failure;
- `5`: unexpected internal error.

See [baseline trust](docs/book/07-baseline.md),
[exit codes](docs/book/09-exit-codes.md), and
[metrics and gates](docs/book/16-metrics-and-quality-gates.md).

## MCP and Agent Surfaces

The optional `codeclone[mcp]` server is read-only with respect to source files,
baselines, canonical/generated reports, and analysis cache data.

Explicit controller and developer contracts may maintain bounded local state:

- session-local runs and review markers;
- ephemeral workspace intent records under `.codeclone/intents/`;
- optional audit evidence under `.codeclone/db/`;
- governed Engineering Memory and projection state under `.codeclone/memory/`;
- optional Platform Observability telemetry under
  `.codeclone/db/platform_observability.sqlite3`.

Engineering Memory mutations must use explicit memory tools. Agent-initiated
mutations are limited to the documented refresh, projection, and draft
proposal contracts; approval, rejection, and archival remain human-governed.
None of this state may alter canonical report identity, baseline trust, cache
compatibility, findings, or edit authorization.

Tool names, parameter fields, response shapes, resource URIs, descriptions, and
error semantics are public surfaces. Keep optional MCP dependencies lazy so the
base package and non-MCP CI do not require them.

See the [MCP interface](docs/book/25-mcp-interface/index.md) and
[MCP contributor guide](docs/guide/mcp/README.md).

## Engineering Memory

Engineering Memory is a local, evidence-linked knowledge store, not a second
analyzer and not analysis cache. It combines governed records with report, git,
documentation, audit, trajectory, Patch Trail, and Experience evidence.

When changing memory behavior:

- preserve deterministic retrieval and stable bounded payloads;
- keep FTS, semantic sidecar, trajectory, and Experience lanes explicit;
- preserve human governance for durable promoted knowledge;
- treat semantic search as optional and keep the default installation free of
  vector-model dependencies;
- keep projection jobs coalesced, watermarked, observable, and independent from
  analysis truth;
- test schema migration, staleness, filtering, ranking, scope, governance, and
  worker lifecycle as applicable.

Start with the [Engineering Memory chapter](docs/book/13-engineering-memory/index.md),
[trajectory and Patch Trail contract](docs/book/13-engineering-memory/trajectory-and-patch-trail.md),
[Experience Layer](docs/book/13-engineering-memory/experience-layer.md), and
[projection jobs](docs/book/13-engineering-memory/projection-jobs.md).

## Platform Observability

Platform Observability is an opt-in developer diagnostics surface for
CodeClone's own execution. It helps investigate slow CLI/MCP operations,
database cost, projection workers, memory pipelines, redundant work, and
cross-process correlations.

It is disabled by default and configured only through environment variables.
It stores bounded local telemetry, normalized literal-free SQL fingerprints,
durations, counters, and optional process metrics. It does not store raw prompt
or MCP payload bodies and has no network exporter.

Most importantly, observer data is **not** repository quality evidence. It must
never affect findings, gates, baseline trust, cache compatibility, memory facts,
permissions, or edit authorization.

Enable it for a local diagnostic run:

```bash
CODECLONE_OBSERVABILITY_ENABLED=1 uv run codeclone .
uv run codeclone observability trace --root .
uv run codeclone observability trace \
  --root . \
  --last 50 \
  --html /tmp/codeclone-observer.html
```

Optional process metrics require the `perf` extra and
`CODECLONE_OBSERVABILITY_PROFILE=1`. Raw payload snapshots are unsupported.
Automatic retention pruning is not currently guaranteed, so developers who
enable persistence own the lifecycle of the local SQLite database.

Instrumentation must be initialized before instrumented stores/connections are
opened, and worker correlation IDs must be propagated rather than synthesized
independently. New spans and counters must remain numeric, bounded,
deterministic in shape, and privacy-safe.

Read the normative [Platform Observability contract](docs/book/26-platform-observability.md)
and the practical [diagnostics guide](docs/guide/observability/diagnostics.md)
before modifying instrumentation, storage, rendering, or MCP projections.

## Native Clients and Integrations

VS Code, Claude Desktop, Claude Code, Codex, Cursor, and the composite GitHub
Action are clients or packaging surfaces over the same CodeClone/MCP contracts.
They must not implement a second analyzer, redefine finding semantics, or
silently drift from MCP tool schemas.

Public commands, views, manifests, bundled skills/rules/hooks, launcher
behavior, trust boundaries, packaged assets, and marketplace metadata require
surface-specific tests and documentation.

Architecture references:

- [VS Code extension](docs/book/integrations/vs-code-extension.md)
- [Claude Desktop bundle](docs/book/integrations/claude-desktop-bundle.md)
- [Claude Code plugin](docs/book/integrations/claude-code-plugin.md)
- [Codex plugin](docs/book/integrations/codex-plugin.md)
- [Cursor plugin](docs/book/integrations/cursor-plugin.md)

For the GitHub Action, never interpolate `${{ inputs.* }}` directly into shell
scripts; pass values through `env:`. Keep subprocess timeouts explicit and
preserve documented output and exit semantics.

## Developer Scripts

The top-level [`scripts/`](scripts/) directory contains developer, docs, and
release utilities. It is not a miscellaneous home for product behavior:
runtime logic belongs in the owning `codeclone/` module and scripts should stay
thin, explicit, and tested.

| Path                                   | Purpose                                                                                          | Important boundary                                                                                                          |
|----------------------------------------|--------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| `scripts/build_docs_example_report.py` | Analyze the repository and stage the live docs example as HTML, JSON, SARIF, and `manifest.json` | Writes generated output, by default under `site/examples/report/live`; use it only for docs example/report publication work |
| `scripts/lint_admonitions.py`          | Validate MkDocs admonition/details indentation                                                   | `--fix` rewrites Markdown; review the resulting diff                                                                        |
| `scripts/launch_mcp`                   | Monorepo adapter that delegates to the shared Codex plugin MCP launcher                          | Not an independent launcher implementation; keep launcher resolution in `plugins/codeclone/scripts/launch_mcp.py`           |
| `scripts/sync_integrations.py`         | Synchronize Codex, Claude Code, Cursor, VS Code, and Claude Desktop distribution repositories    | Maintainer/release tool that deletes and recopies managed target paths; always dry-run first                                |
| `scripts/integration_dist/*`           | Distribution-only README, `.gitignore`, and marketplace overlays used by storefront sync         | Source-controlled release inputs, not generated scratch files                                                               |
| `scripts/__init__.py`                  | Package marker for importing script helpers in tests                                             | Not a command-line entrypoint                                                                                               |

### Docs utilities

When changing the live sample report or its publication path:

```bash
uv run python scripts/build_docs_example_report.py \
  --output-dir site/examples/report/live
uv run --with zensical==0.0.46 zensical build --clean --strict
```

The generator runs CodeClone against the repository, stages its output in a
temporary directory, then copies only the documented artifacts to the
destination. Changes require the relevant report/HTML tests plus
`tests/test_docs_example_report.py`.

Validate admonition indentation without writing:

```bash
uv run scripts/lint_admonitions.py docs/
```

Apply its deterministic indentation repair only when needed:

```bash
uv run scripts/lint_admonitions.py docs/ --fix
```

The pre-commit hook uses `--fix`, so docs commits must be re-reviewed after the
hook runs.

### Storefront synchronization

`scripts/sync_integrations.py` mirrors monorepo integration sources into sibling
git repositories named `codeclone-codex`, `codeclone-claude-code`,
`codeclone-cursor`, `codeclone-vscode`, and `codeclone-claude-desktop`. It also
writes a `SYNC_MANIFEST.json` containing source commit and package provenance.

Run it from the monorepo root and inspect a dry run first:

```bash
uv run python scripts/sync_integrations.py \
  --dry-run \
  --all \
  --base-dir ..
```

Only after reviewing the plan should a maintainer perform a write:

```bash
uv run python scripts/sync_integrations.py --all --base-dir ..
```

The script refuses a dirty source tree by default, validates target repository
names and containment, rejects copied symlinks, and writes the manifest
atomically. `--allow-dirty` is an emergency override, not a normal release
workflow; its dirty provenance is recorded in the manifest. Sync each target,
inspect its diff, run its native checks, and commit/push each distribution
repository separately.

Cursor and Claude Code have intentional launcher overrides: their monorepo
launchers are thin delegates, while standalone distributions receive the full
shared launcher implementation. Do not replace this with a blind directory
copy.

Changes to sync logic, layouts, deny lists, launchers, or
`scripts/integration_dist/*` require:

```bash
uv run pytest -q tests/test_sync_integrations.py
```

The full operational and post-sync checklist is in
[`docs/releasing.md`](docs/releasing.md).

## Development Setup

CodeClone supports Python 3.10 through 3.14.

```bash
git clone https://github.com/orenlab/codeclone.git
cd codeclone
uv sync --extra dev --extra mcp --extra token-bench
uv run pre-commit install
```

`.pre-commit-config.yaml` installs both `pre-commit` and `pre-push` hooks by
default. Do not use `--no-verify` to bypass them; fix the failure or document a
genuine infrastructure blocker for maintainers.

The semantic and performance extras are intentionally optional. Install them
only for work that needs those paths, for example:

```bash
uv sync --extra dev --extra mcp --extra semantic-local --extra perf
```

## Required Validation

The pre-commit stage runs repository hygiene checks, Ruff formatting and lint,
Mypy, baseline-aware `codeclone . --ci`, and the docs admonition fixer when
matching Markdown changed:

```bash
uv run pre-commit run --all-files
```

Some hooks modify files (`end-of-file-fixer`, trailing whitespace, line endings,
Ruff format, and docs admonition repair). Always inspect `git diff` again after
the hook completes.

The command above runs the **pre-commit stage only**. It does not run the
pre-push pytest hook. Run that stage explicitly before pushing:

```bash
uv run pre-commit run --hook-stage pre-push --all-files
```

The pre-push hook executes the full test suite with package coverage of at
least 99%. Its underlying CI command is:

```bash
uv run pytest \
  --cov=codeclone \
  --cov-report=term-missing \
  --cov-fail-under=99
```

CI runs this suite on Python 3.10, 3.11, 3.12, 3.13, and 3.14. A test that only
passes on the contributor's interpreter is not sufficient.

Run focused tests while developing, but do not use them as a substitute for
the required full validation when the change can affect shared behavior.

### Contract-specific checks

For MCP changes:

```bash
uv run pytest -q tests/test_mcp_service.py tests/test_mcp_server.py
```

For Engineering Memory, semantic retrieval, trajectory, Experience, or
projection-job changes, run the nearest owning modules described in
[testing as specification](docs/book/23-testing-as-spec.md), including the
relevant `tests/test_memory_*.py`, `tests/test_semantic_*.py`, and MCP memory
contract tests.

For Platform Observability changes:

```bash
uv run pytest -q tests/test_observability_*.py
```

For documentation, navigation, publishing, or sample-report changes:

```bash
uv run --with zensical==0.0.46 zensical build --clean --strict
```

For VS Code extension changes:

```bash
node --check extensions/vscode-codeclone/src/support.js
node --check extensions/vscode-codeclone/src/mcpClient.js
node --check extensions/vscode-codeclone/src/extension.js
node --test extensions/vscode-codeclone/test/*.test.js
node extensions/vscode-codeclone/test/runExtensionHost.js
```

If VS Code packaging metadata or assets changed, also package a `.vsix` with
`vsce package --out /tmp/codeclone.vsix`.

For Claude Desktop bundle changes:

```bash
node --check extensions/claude-desktop-codeclone/server/index.js
node --check extensions/claude-desktop-codeclone/src/launcher.js
node --check extensions/claude-desktop-codeclone/scripts/build-mcpb.mjs
node --test extensions/claude-desktop-codeclone/test/*.test.js
node extensions/claude-desktop-codeclone/scripts/build-mcpb.mjs \
  --out /tmp/codeclone-claude-desktop.mcpb
```

For Codex plugin changes:

```bash
python3 -m json.tool plugins/codeclone/.codex-plugin/plugin.json \
  >/tmp/codeclone-codex-plugin.json
python3 -m json.tool plugins/codeclone/.mcp.json \
  >/tmp/codeclone-codex-mcp.json
python3 -m json.tool .agents/plugins/marketplace.json \
  >/tmp/codeclone-codex-marketplace.json
uv run pytest -q tests/test_codex_plugin.py
```

For Claude Code plugin changes:

```bash
python3 -m json.tool \
  plugins/claude-code-codeclone/.claude-plugin/plugin.json \
  >/tmp/codeclone-claude-code-plugin.json
python3 -m json.tool plugins/claude-code-codeclone/.mcp.json \
  >/tmp/codeclone-claude-code-mcp.json
python3 -m json.tool scripts/integration_dist/marketplace.claude-code.json \
  >/tmp/codeclone-claude-code-marketplace.json
claude plugin validate plugins/claude-code-codeclone
uv run pytest -q tests/test_claude_code_plugin.py
```

For Cursor plugin changes:

```bash
uv run pytest -q tests/test_cursor_plugin.py tests/test_cursor_plugin_hooks.py
```

For GitHub Action helper changes:

```bash
uv run pytest -q tests/test_github_action_helpers.py
```

The change-routing matrix in [`AGENTS.md`](AGENTS.md) is authoritative when a
change spans more than one contract or integration.

## Test Policy

- Put tests beside the contract they specify, using the owning module's test
  file and naming conventions.
- Prefer behavior and invariant assertions over implementation-detail checks.
- Cover normal mode, gating mode, error paths, determinism, and legacy or
  untrusted states where relevant.
- Public payload changes require contract tests, not only unit tests.
- Avoid sleeps, unstable filesystem ordering, machine-local paths, and
  network-dependent assertions.
- Coverage is a guardrail, not a reason to create artificial test modules or
  tests that merely execute lines without asserting behavior.
- A bug fix should normally include a regression test that fails before the
  fix and passes after it.

## Pull Requests

A pull request should state:

- the problem and user-visible outcome;
- files and ownership boundaries affected;
- contract, schema, baseline, cache, report, CLI, MCP, memory, observability, or
  integration implications;
- tests and validation commands run;
- documentation and migration/release-note impact;
- material use of coding agents or generated content.

Keep unrelated refactors and generated churn out of the patch. Do not claim a
finding is new, fixed, regression-free, or patch-local without the evidence
required by the relevant contract.

Maintainers may request narrower scope, stronger negative tests, before/after
evidence, or a versioned migration even when CI is green.

## Commit Messages

Use the repository's Conventional Commits style:

- `type(scope): imperative summary`;
- lowercase type such as `feat`, `fix`, `docs`, `test`, or `chore`;
- a narrow scope when useful;
- separate commits for unrelated work;
- a concise subject with explanatory detail in the body when needed.

Examples:

- `fix(memory): preserve lane filters during semantic fusion`
- `feat(observability): correlate projection worker spans`
- `docs(contributing): align developer workflow with current surfaces`

## Code Style

- Python 3.10 through 3.14
- required type annotations and precise types
- minimal use of `Any`
- `ruff format`, `ruff check`, and `mypy` must pass
- explicit, readable control flow over clever implicit behavior
- comments only where they clarify non-obvious reasoning or contracts
- deterministic sorting and serialization at all public boundaries

Follow existing local patterns before introducing new abstractions.

## Releases and Changelog

User-facing features, compatibility changes, migrations, and notable developer
surfaces belong in `CHANGELOG.md`. Routine fixes made during the current
development cycle do not need individual changelog entries unless they alter a
published contract or require user action.

Release work must follow [`docs/releasing.md`](docs/releasing.md), including
artifact, installation, and publishing checks for every affected surface.

## License

By contributing code to CodeClone, you agree that the contribution is licensed
under **MPL-2.0**.

Documentation contributions are licensed under **MIT**.
