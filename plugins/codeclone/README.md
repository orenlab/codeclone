# CodeClone for Codex

Native Codex plugin — **Structural Change Controller for AI-assisted Python
development** — over `codeclone-mcp`.

Same canonical MCP surface used by CLI, VS Code, Claude Desktop, and Claude Code.
Repository read-only (source, baselines, cache, canonical reports); local stdio
only. The bundled launcher exposes the full default agent MCP surface, including
change-control, Engineering Memory, Platform Observability, and session tools —
ephemeral coordination under
`.codeclone/intents/` and optional audit records when enabled.
Current-run metric surfaces from the local `codeclone-mcp` version flow through
directly, including `Coverage Join` facts and the optional `coverage` help topic.

## What ships here

| File                                       | Purpose                                                             |
|--------------------------------------------|---------------------------------------------------------------------|
| `.codex-plugin/plugin.json`                | Plugin metadata, prompts, and instructions                          |
| `.mcp.json`                                | Local stdio MCP definition                                          |
| `scripts/launch_mcp`                       | Shell-free workspace-first launcher bootstrap                       |
| `skills/codeclone-review/`                 | Conservative-first full review skill                                |
| `skills/codeclone-hotspots/`               | Quick hotspot discovery skill                                       |
| `skills/codeclone-production-triage/`      | Production-first baseline triage skill                              |
| `skills/codeclone-architecture-triage/`    | Ranked architecture problem triage skill                            |
| `skills/codeclone-blast-radius/`           | Read-only blast-radius inspection skill                             |
| `skills/codeclone-change-control/`         | Intent-first change workflow skill                                  |
| `skills/codeclone-implementation-context/` | Bounded `get_implementation_context` playbook                       |
| `skills/codeclone-engineering-memory/`     | Engineering Memory retrieval and draft writes                       |
| `skills/codeclone-platform-observability/` | Maintainer-only observer diagnostics (not for end-user repo review) |
| `assets/`                                  | Plugin branding                                                     |

Nine skills ship in the plugin (review, hotspots, production-triage, architecture-triage,
blast-radius, change-control, engineering-memory, implementation-context,
platform-observability).

`plugin.json` keeps the machine identifier as lowercase `codeclone`; the
user-facing label stays in `interface.displayName` as `CodeClone`.

## Install

Install the distribution package from the Codex marketplace:

```bash
codex plugin marketplace add orenlab/codeclone-codex
codex plugin add codeclone@orenlab-codeclone
```

This plugin does not install the MCP server binary. Install CodeClone with the
MCP extra in the workspace or globally.

Recommended workspace-local setup:

```bash
uv venv
uv pip install --python .venv/bin/python "codeclone[mcp]"
.venv/bin/codeclone-mcp --help
```

If your workspace uses Poetry, install CodeClone into that Poetry environment.

Global fallback:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --help
```

The bundled Codex launcher is a small repo-local Python wrapper, not a shell
snippet. It prefers a workspace `.venv`, then the current Poetry environment,
then `codeclone-mcp` from `PATH`, without relying on `sh -lc`.

`.agents/plugins/marketplace.json` is the monorepo-local source entry used for
development and distribution packaging. Public installs should use
`codex plugin marketplace add orenlab/codeclone-codex`, followed by
`codex plugin add codeclone@orenlab-codeclone`.

The plugin does not rewrite `~/.codex/config.toml`.

If you prefer manual MCP registration instead:

```bash
codex mcp add codeclone -- codeclone-mcp --transport stdio
```

## Skills

**codeclone-review** — full structural review: conservative first pass,
baseline-aware triage, changed-files review, deeper exploratory follow-up,
current-run metrics surfaces.

**codeclone-hotspots** — quick quality snapshot: health check, top risks,
single-metric queries, pre-merge sanity checks, coverage/adoption/API snapshots.

**codeclone-production-triage** — production-first baseline snapshot: health,
counts, top production hotspots, regressions vs baseline, recommended next action.

**codeclone-blast-radius** — read-only blast-only inspection before editing
specific files; use `codeclone-implementation-context` for the bundled projection.

**codeclone-change-control** — intent-first workflow for repository edits:
workspace intent check, blast radius, patch contract verification, claim guard,
and review receipt.

**codeclone-engineering-memory** — ranked scope context before edits, FTS search,
optional semantic blend (`semantic=true` on `mode=search` when the server index
is built), draft candidates, and finish proposals. Human governance via supported
IDE Memory views or CLI `--i-know-what-im-doing`.

**codeclone-platform-observability** — **maintainer-only**: diagnose CodeClone's
own runtime via `query_platform_observability` after explicit
`CODECLONE_OBSERVABILITY_ENABLED=1`. Not for end-user repository review.

## Links

- [Codex plugin guide](https://orenlab.github.io/codeclone/guide/integrations/codex/setup/)
- [MCP usage guide](https://orenlab.github.io/codeclone/guide/mcp/)
- [Privacy Policy](https://orenlab.github.io/codeclone/privacy-policy/)
