# Cursor Plugin

CodeClone ships a native Cursor plugin. Source lives in
`plugins/cursor-codeclone/`; the plugin bundles an MCP server definition,
five skills, one agent, two rules, and two hooks.

## What ships in the plugin

| Component | Path | Purpose |
|-----------|------|---------|
| `.cursor-plugin/plugin.json` | Manifest | Plugin metadata and component declarations |
| `mcp.json` | MCP server | Local stdio `codeclone-mcp` server definition |
| `skills/codeclone-review/` | Skill | Conservative-first full structural review |
| `skills/codeclone-hotspots/` | Skill | Quick hotspot discovery and health snapshot |
| `skills/codeclone-change-control/` | Skill | Intent-first change workflow with blast radius and verification |
| `skills/blast-radius/` | Skill | Standalone blast radius inspection before edits |
| `skills/production-triage/` | Skill | Fast production-focused triage and next-action recommendation |
| `agents/structural-reviewer.md` | Agent | Deterministic structural code reviewer backed by MCP tools |
| `rules/codeclone-workflow.mdc` | Rule | MCP workflow discipline (always active) |
| `rules/codeclone-python.mdc` | Rule | Python file context (auto-triggers on `**/*.py`) |
| `hooks/hooks.json` | Hooks | Post-edit re-analysis reminder and session cleanup check |
| `assets/` | Branding | Plugin logo and icon |

## Install

The plugin expects a local `codeclone-mcp` launcher. Install CodeClone with
the MCP extra:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --help
```

### Project-level setup

Symlink the plugin into the project `.cursor/` directory:

```bash
mkdir -p .cursor/skills .cursor/rules .cursor/agents

# Skills
for d in plugins/cursor-codeclone/skills/*/; do
    ln -sfn "$(pwd)/$d" ".cursor/skills/$(basename $d)"
done

# Rules
for f in plugins/cursor-codeclone/rules/*.mdc; do
    ln -sfn "$(pwd)/$f" ".cursor/rules/$(basename $f)"
done

# MCP server
ln -sfn "$(pwd)/plugins/cursor-codeclone/mcp.json" .cursor/mcp.json

# Agent
ln -sfn "$(pwd)/plugins/cursor-codeclone/agents/structural-reviewer.md" \
    .cursor/agents/structural-reviewer.md
```

Add `.cursor/` to `.gitignore` if it is not already there.

### Personal (global) setup

```bash
ln -sfn /path/to/codeclone/plugins/cursor-codeclone \
    ~/.cursor/plugins/local/codeclone
```

## Skills

### codeclone-production-triage

Fast production-focused first pass: health score, finding counts, top hotspots,
baseline status, and recommended next action. Two MCP calls:
`analyze_repository` then `get_production_triage`.

### codeclone-hotspots

Quick quality snapshot: health check, top risks, single-metric queries. The
cheapest useful path for answering ad-hoc questions about repository quality.

### codeclone-blast-radius

Standalone blast radius inspection before editing files. Shows dependents,
clone cohort, risk signals, do-not-touch boundaries, and guardrails. Read-only
— does not declare intent or start a change workflow.

### codeclone-review

Full structural review: clone triage, changed-scope review, health-oriented
refactor planning. Starts conservative with default thresholds, supports
deeper follow-up with lowered thresholds and run comparison.

### codeclone-change-control

Intent-first change workflow for repository edits. Declares scope before
editing, maps blast radius, verifies the patch against the contract, generates
a review receipt, and validates cited review claims. This is the governance
skill — use it whenever the task requires changing files.

## Agent

### structural-reviewer

Deterministic structural code reviewer that uses CodeClone MCP tools to assess
clone risk, complexity hotspots, coupling, and blast radius. Reports findings
with file paths and evidence, not opinions. Does not modify files or declare
intent.

## Rules

- **codeclone-workflow.mdc** (always active) — MCP workflow discipline: use MCP
  tools only, pass absolute roots, prefer `get_production_triage` after
  analysis, do not fall back to CLI or local report files.
- **codeclone-python.mdc** (glob: `**/*.py`) — auto-triggers when Python files
  are in context: run analysis before structural changes, check blast radius,
  do not introduce regressions.

## Hooks

- **afterFileEdit** — when a Python file is edited, reminds the agent to
  re-run analysis and check intent status.
- **stop** — at session end, warns if change intents were declared but not
  cleared.

## Runtime model

Additive — the plugin provides a local MCP definition, five skills, one agent,
two rules, and two hooks. New canonical MCP surfaces from the local
`codeclone-mcp` version flow through directly. The plugin does not install a
second server binary or mutate Cursor settings.

## Current limits

- If you already configured `codeclone-mcp` manually in Cursor MCP settings,
  keep only one setup path to avoid duplicate MCP surfaces.
- The bundled `mcp.json` expects `codeclone-mcp` on `PATH` or configured with
  an absolute path.
- Hooks use shell scripts and require `bash` and `grep`.

## Further reading

- [MCP usage guide](mcp.md)
- [MCP interface contract](book/20-mcp-interface.md)
- [Structural Change Controller](book/24-structural-change-controller.md)
- [Cursor plugin contract](book/25-cursor-plugin.md)
