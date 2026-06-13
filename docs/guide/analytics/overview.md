# Corpus Analytics

Use Corpus Analytics when you want **offline clustering of historical change-control
intents** — for example to compare agent workflow cohorts, inspect outliers, or
export HTML/JSON summaries for maintainer review.

## Prerequisites

1. A repository with audit enabled and historical `intent.declared` events.
2. Engineering Memory trajectory projection (optional but improves selection).
3. Install optional dependencies:

```bash
uv sync --extra analytics
```

## Quick start

Build snapshot, embeddings, and a recommended clustering run in one step:

```bash
codeclone analytics build --root . --use-recommended
```

Write artifacts to explicit paths:

```bash
codeclone analytics build \
  --root . \
  --representation description \
  --html-out /tmp/corpus-clusters.html \
  --json-out /tmp/corpus-clusters.json
```

## Step-by-step

```bash
# 1. Immutable snapshot from audit + trajectory (+ optional registry overlay)
codeclone analytics snapshot --root .

# 2. Analytics embeddings (separate LanceDB sidecar)
codeclone analytics embed --root . --snapshot-id SNAPSHOT_ID

# 3. Cluster (add --sweep for parameter sweep)
codeclone analytics cluster \
  --root . \
  --snapshot-id SNAPSHOT_ID \
  --embedding-generation-id GENERATION_ID

# 4. Inspect runs
codeclone analytics clusters --root . --snapshot-id SNAPSHOT_ID
codeclone analytics cluster-show \
  --root . --snapshot-id SNAPSHOT_ID --run-id RUN_ID
```

## Configuration

Defaults live in `[tool.codeclone.analytics]` inside `pyproject.toml`. See
[Corpus Analytics contract](../../book/27-corpus-analytics.md) for the full table.

## What this is not

- Not a second analyzer — it does not replace `codeclone` structural reports.
- Not Engineering Memory semantic search — vectors are stored separately.
- Not MCP-visible in Slice 1 — CLI only.

Contract reference: [27-corpus-analytics.md](../../book/27-corpus-analytics.md).
