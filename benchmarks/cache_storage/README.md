# Phase 39K K0 cache-storage bake-off

This directory contains benchmark-only evidence for the 39K storage decision.
Nothing under `benchmarks/cache_storage/` is imported by production code.

The measured candidates are exactly:

1. `bucketed_chunks` — 256 deterministic content-addressed buckets plus one
   atomic manifest;
2. `path_shards` — one immutable content-addressed entry per repository path
   plus one atomic manifest;
3. `sqlite_wal` — one row per path in SQLite WAL, retained only as the
   benchmark control required by the brief.

`monolith_reference` records the pre-39K full-document behavior for regression
guardrails, including canonical payload signing and signature verification. It
is not a fourth candidate.

The harness reads a trusted current cache-v3 document, verifies its signature,
and uses the embedded final 39J entry wire without translating it. It measures
three corpora: 64 entries, the current repository cache, and a deterministic
10,000-path corpus built from the smallest valid current entry wire. Every
candidate runs the complete recovery/concurrency matrix from the 39K brief.
Content-addressed generations are immutable during a benchmark scenario;
reclamation is deliberately deferred so a reader holding the previous atomic
manifest cannot lose files underneath its read.

Run from the repository root with the project virtual environment:

```bash
.venv/bin/python -m benchmarks.cache_storage.bakeoff \
  --source-cache .codeclone/cache.json \
  --repository-root . \
  --output benchmarks/cache_storage/results.json \
  --repeats 3
```

Each scenario executes in a fresh child process. `elapsed_ns` excludes source
cache loading and corpus construction, while `peak_rss_bytes` includes them so
the memory number represents the complete worker footprint. `logical_syscalls`
counts adapter-visible filesystem or SQLite operations; `read_bytes` and
`write_bytes` count application bytes passed through those operations. These
are reproducible logical-I/O metrics, not privileged kernel tracing.

`results.json` is the immutable K0 decision input. Its
`selection_status` remains `awaiting_maintainer`; the harness computes
guardrail verdicts but does not select or implement a production backend.

## K0 outcome

The recorded matrix contains 342 raw samples and 114 aggregates. All raw
samples and all 54 candidate recovery aggregates pass. Incremental-write,
memory, and recovery guardrails pass for every candidate and corpus, but no
candidate passes the warm median and p95 guardrails across all three corpora.
SQLite passes the complete row only for `synthetic_10000` and remains
control-only. No production cutover is authorized by this checkpoint.
