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
codeclone analytics build --root . --sweep --use-recommended
```

`--use-recommended` requires `--sweep`. It renders the heuristic winner for
inspection; it does **not** set `selected_by_maintainer`.

Write a detailed single-run report to explicit paths:

```bash
codeclone analytics build \
  --root . \
  --representation description \
  --html-out /tmp/corpus-clusters.html \
  --json-out /tmp/corpus-clusters.json
```

Write a sweep comparison without choosing a primary detail view:

```bash
codeclone analytics build \
  --root . \
  --sweep \
  --html-out /tmp/corpus-sweep.html \
  --json-out /tmp/corpus-sweep.json
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

# 5. Record an explicit maintainer choice
codeclone analytics cluster --root . --select-run RUN_ID
```

## Configuration

Defaults live in `[tool.codeclone.analytics]` inside `pyproject.toml`. See
[Corpus Analytics contract](../../book/27-corpus-analytics.md) for the full table.
The historical audit source follows top-level `[tool.codeclone].audit_path`.

## Reproducibility

Exports persist snapshot and embedding manifests, vector digests, requested and
effective parameters, fixed PCA/HDBSCAN settings, package versions, and the
random seed. Unless the model revision and artifact fingerprint are known,
CodeClone explicitly reports that full vector reproducibility is not guaranteed
from the model id alone.

Existing embedding generations created under an incompatible embedding contract
are rejected. Run `embed` again for the same snapshot to create a compatible
generation.

## Failure behavior

- Expected input, capability, schema, and artifact-integrity errors exit with
  code `2` and no traceback.
- A clustering run is persisted as `running`, then becomes `completed` or
  `failed`; failed runs contain no committed assignments or summaries.
- JSON and HTML outputs are written atomically.
- Snapshot, embed, cluster, and report spans are recorded only when
  `CODECLONE_OBSERVABILITY_ENABLED=1`.

## What this is not

- Not a second analyzer — it does not replace `codeclone` structural reports.
- Not Engineering Memory semantic search — vectors are stored separately.
- Not MCP-visible in Slice 1 — CLI only.

Contract reference: [27-corpus-analytics.md](../../book/27-corpus-analytics.md).
