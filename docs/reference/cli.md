---
title: "CLI reference"
audience: public
doc_type: reference
status: draft
source_commit: "d88c17f0f19cf753b9d43870528e0747b3161b9c"
---

## Overview

CodeClone is a deterministic structural change controller for AI-assisted Python development. The default invocation runs full analysis on a repository:

```bash
codeclone [options] [root]
```

The root directory defaults to the current directory. Analysis produces findings on structural clones, code metrics, dependencies, and code health. Reporting formats include JSON, HTML, Markdown, SARIF, and plain text.

Specialized subcommands manage setup, engineering memory, and analytics. Exit code 0 indicates success; 2 signals contract violations; 3 indicates gating failures; 5 is an internal error.

## Global options

### Target and analysis scope

| Option | Description |
|--------|-------------|
| `root` | Project root directory. Defaults to `.` |
| `--min-loc MIN_LOC` | Minimum Lines of Code for clone analysis. Default: 10 |
| `--min-stmt MIN_STMT` | Minimum AST statement count for clone analysis. Default: 6 |
| `--processes PROCESSES` | Parallel worker processes. Default: 4 |
| `--changed-only` | Limit findings to files in a git diff |
| `--diff-against REF` | Use `git diff --name-only <REF>` to determine changed files |
| `--paths-from-git-diff REF` | Shorthand for `--changed-only --diff-against REF` |

### Baseline and cache

| Option | Description |
|--------|-------------|
| `--baseline [FILE]` | Clone baseline path. Default: `codeclone.baseline.json` |
| `--max-baseline-size-mb MB` | Maximum baseline size. Default: 5 |
| `--update-baseline` | Overwrite baseline with current results |
| `--metrics-baseline [FILE]` | Metrics baseline path. Default: `codeclone.baseline.json` |
| `--update-metrics-baseline` | Overwrite metrics baseline with current metrics |
| `--cache-path [FILE]` | Cache file path. Default: `.codeclone/cache.json` |
| `--cache-dir [FILE]` | Legacy alias for `--cache-path` |
| `--max-cache-size-mb MB` | Maximum cache size. Default: 50 |

### Verification and gates

| Option | Description |
|--------|-------------|
| `--blast-radius FILE [FILE ...]` | Show structural impact for given files |
| `--patch-verify` | Verify current patch against baseline budget |
| `--strictness LEVEL` | Strictness profile: `ci`, `strict`, or `relaxed`. Default: `ci` |
| `--ci` | Enable CI preset (`--fail-on-new --no-color --quiet`) |
| `--api-surface` | Collect public API surface facts for compatibility review |
| `--coverage FILE` | Join external Cobertura XML line coverage |

### Quality gates (fail on violation)

| Option | Description |
|--------|-------------|
| `--fail-on-new` | Exit 3 if new clones found vs. baseline |
| `--fail-on-new-metrics` | Exit 3 if metrics violations appear vs. baseline |
| `--fail-threshold MAX_CLONES` | Exit 3 if total clone groups exceed value |
| `--fail-complexity [CC_MAX]` | Exit 3 if cyclomatic complexity exceeds threshold. Default if enabled: 20 |
| `--fail-coupling [CBO_MAX]` | Exit 3 if class coupling exceeds threshold. Default if enabled: 10 |
| `--fail-cohesion [LCOM4_MAX]` | Exit 3 if class cohesion exceeds threshold. Default if enabled: 4 |
| `--fail-cycles` | Exit 3 if circular dependencies detected |
| `--fail-dead-code` | Exit 3 if dead code detected |
| `--fail-health [SCORE_MIN]` | Exit 3 if health score below threshold. Default if enabled: 60 |
| `--fail-on-typing-regression` | Exit 3 if typing coverage regresses |
| `--fail-on-docstring-regression` | Exit 3 if docstring coverage regresses |
| `--fail-on-api-break` | Exit 3 if public API removals detected |
| `--fail-on-untested-hotspots` | Exit 3 if risk-level functions have insufficient coverage. Requires `--coverage` |
| `--min-typing-coverage PERCENT` | Exit 3 if parameter typing coverage below threshold |
| `--min-docstring-coverage PERCENT` | Exit 3 if public docstring coverage below threshold |
| `--coverage-min PERCENT` | Coverage threshold for untested hotspots. Default: 50 |

### Analysis stages

| Option | Description |
|--------|-------------|
| `--skip-metrics` | Run clone-only mode, skip full metrics |
| `--skip-dead-code` | Skip dead code detection |
| `--skip-dependencies` | Skip dependency graph analysis |

### Workspace and audit

| Option | Description |
|--------|-------------|
| `--session-stats` | Show workspace session status (read-only) |
| `--audit` | Show local Controller audit trail (read-only) |
| `--audit-json` | Output audit payload footprint as JSON. Implies `--audit` |

## Commands

### `setup [action]`

Initialize or inspect repository readiness.

**Actions:**
- `status` (default): Show readiness status
- `doctor`: Diagnostic check
- `plan`: Preview setup steps
- `apply`: Execute setup plan
- `wizard`: Interactive setup guide

**Options:**
- `--json`: Emit JSON output
- `--dry-run`: Preview changes without modifying files (apply only)
- `-y, --yes`: Skip confirmation prompt (apply only)
- `--plan-id PLAN_ID`: For apply, verify plan matches this ID
- `--root ROOT`: Repository root path

### `memory [subcommand]`

Manage engineering memory (durable knowledge base).

**Subcommands:**
- `init`: Initialize engineering memory
- `status`: Show memory status
- `for-path`: List records for a source path
- `search`: Search records by keyword
- `stale`: List stale records
- `vacuum`: Purge expired records
- `coverage`: Show memory coverage
- `review-candidates`: List draft candidates
- `approve`: Approve a draft record
- `reject`: Reject a draft record
- `archive`: Archive an active record
- `semantic`: Semantic index management (status / rebuild / search)
- `trajectory`: Trajectory projections (status / rebuild / list / search / show / agents / anomalies / dashboard / export)
- `jobs`: Projection rebuild jobs (status / enqueue / run-once / list)

### `analytics [subcommand]`

Manage and query code analytics.

**Subcommands:**
- `snapshot`: Capture current metrics snapshot
- `embed`: Embed code representations
- `cluster`: Clustering operations
- `build`: Build analytics indices
- `clusters`: List available clusters
- `cluster-show`: Show cluster details
- `outliers`: Identify outlier code
- `profiles`: Show analytics profiles

### `observability [subcommand]`

Observe CodeClone runtime behavior (maintainer only).

## Machine-readable output

Reports are written to `.codeclone/report.<ext>` by default unless FILE is specified.

| Flag | Format | Default path |
|------|--------|--------------|
| `--json [FILE]` | Canonical JSON report | `.codeclone/report.json` |
| `--html [FILE]` | Interactive HTML | `.codeclone/report.html` |
| `--md [FILE]` | Markdown | `.codeclone/report.md` |
| `--sarif [FILE]` | SARIF 2.1.0 | `.codeclone/report.sarif` |
| `--text [FILE]` | Plain text | `.codeclone/report.txt` |

**Report options:**
- `--timestamped-report-paths`: Append UTC timestamp to default report filenames
- `--open-html-report`: Open HTML report in default browser (requires `--html`)

**Output formatting:**
- `--no-progress`: Disable progress output (recommended for CI)
- `--no-color`: Disable ANSI colors
- `--quiet`: Reduce output to warnings and errors
- `--verbose`: Include detailed identifiers for new findings
- `--debug`: Print debug details and traceback on error

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Contract error: invalid baseline, incompatible versions, or unreadable sources in CI/gating mode |
| 3 | Gating failure: new clones, threshold violations, or metrics regression |
| 5 | Internal error: unexpected exception |

## Examples

```bash
# Basic analysis on current directory
codeclone

# Analysis with baseline update
codeclone --update-baseline

# CI mode with fail-on-new check
codeclone --ci --fail-on-new

# Changed files only, with HTML report
codeclone --paths-from-git-diff origin/main --html

# Patch verification against baseline
codeclone --patch-verify --strictness strict

# Show structural impact of specific files
codeclone --blast-radius src/core/engine.py src/core/parser.py

# Quality gates: fail on complexity or new clones
codeclone --fail-complexity 20 --fail-on-new

# With external coverage analysis
codeclone --coverage coverage.xml --fail-on-untested-hotspots

# Memory workflow
codeclone memory status
codeclone memory for-path src/core/
codeclone memory search "clustering algorithm"

# Setup readiness check
codeclone setup status
codeclone setup plan
codeclone setup apply --yes
```

## Workflow

The typical workflow combines analysis, baseline updates, and quality gates:

```mermaid
graph LR
  A["codeclone [root]"] --> B{Has baseline?}
  B -->|No| C["--update-baseline"]
  B -->|Yes| D["--patch-verify"]
  C --> E["Save baseline"]
  D --> F{Regression<br/>detected?}
  F -->|Yes| G["Exit 3"]
  F -->|No| H["Exit 0"]
```

For CI/CD pipelines, use the `--ci` preset with appropriate gates:

```bash
codeclone --ci --fail-on-new --fail-complexity 20
```

For pull request analysis, focus on changed files and verify against the merge-base baseline:

```bash
codeclone --paths-from-git-diff origin/main --patch-verify
```

Engineering memory enables persistent, evidence-linked annotations across changesets:

```bash
codeclone memory search "refactor_domain_boundary"
codeclone memory for-path src/domain/
```
