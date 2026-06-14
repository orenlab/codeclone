<!-- doc-scope: COMPATIBILITY AND VERSIONING RULES.
     owns: python-tag policy, schema version rules, fingerprint version,
       breaking-change criteria.
     does-not-own: baseline schema (→ 07), cache schema (→ 08),
       report schema (→ 05). -->

# 24. Compatibility and Versioning

## Purpose

Define when to bump baseline/cache/report/fingerprint versions and how runtime
compatibility is enforced.

## Public surface

- Version constants: `codeclone/contracts/__init__.py`
- Clone baseline compatibility:
  `codeclone/baseline/clone_baseline.py:Baseline.verify_compatibility`
- Metrics baseline compatibility:
  `codeclone/baseline/metrics_baseline.py:MetricsBaseline.verify_compatibility`
- Cache compatibility: `codeclone/cache/store.py:Cache.load`
- Report schema assignment:
  `codeclone/report/document/builder.py:build_report_document`
- MCP public surface: `codeclone/surfaces/mcp/server.py`,
  `codeclone/surfaces/mcp/service.py`

## Data model

Current contract versions:

- `BASELINE_SCHEMA_VERSION = "2.1"`
- `BASELINE_FINGERPRINT_VERSION = "1"`
- `CACHE_VERSION = "2.8"`
- `REPORT_SCHEMA_VERSION = "2.11"`
- `METRICS_BASELINE_SCHEMA_VERSION = "1.2"`
- `ENGINEERING_MEMORY_SCHEMA_VERSION = "1.7"`
- `PATCH_TRAIL_SCHEMA_VERSION = "1"` (finish-time Patch Trail JSON; audit + SQLite sidecar)
- `TRAJECTORY_EXPORT_SCHEMA_VERSION = "2"` (JSONL export rows; `codeclone/memory/trajectory/profiles.py`)
- `TRAJECTORY_PROJECTION_VERSION = "trajectory-v3"` (derived trajectory rows)
- `TRAJECTORY_QUALITY_SCORE_VERSION = "2"` (quality contract formula)
- `EXPERIENCE_DISTILLATION_VERSION = "experience-v1"` (derived Experience rows)
- `SEMANTIC_INDEX_FORMAT_VERSION = "1"` (LanceDB sidecar; separate from SQLite memory schema)
- `PLATFORM_OBSERVABILITY_SCHEMA_VERSION = "1.0"` (dev-only telemetry SQLite)
- `CORPUS_ANALYTICS_STORE_SCHEMA_VERSION = "1.1"` (corpus analytics SQLite)
- `CORPUS_EXPORT_SCHEMA_VERSION = "1.2"` (clustering JSON export)
- `CORPUS_REPRESENTATION_CONTRACT_VERSION = "3"` (intent representation payloads)
- `CORPUS_EMBEDDING_CONTRACT_VERSION = "2"` (analytics embedding sidecar)

Refs:

- `codeclone/contracts/__init__.py`

## Contracts

Version bump rules:

- bump **baseline schema** only for clone-baseline JSON layout/type changes
- bump **fingerprint version** when clone identity semantics change
- bump **cache schema** for cache wire-format or compatibility-semantics changes
- bump **report schema** for canonical report document shape/meaning changes
- bump **metrics-baseline schema** only for standalone metrics-baseline payload changes
- bump **engineering memory schema** for SQLite DDL / governed record-shape changes
  (`codeclone/memory/schema_migrate.py`) — **`1.4`** added Patch Trail
  persistence, **`1.5`** quality scoring, **`1.6`** Experience tables, and
  **`1.7`** the projection-job flush-scheduling column (`flush_claimed_by`)
- bump **patch trail schema** (`PATCH_TRAIL_SCHEMA_VERSION`) when finish-time Patch
  Trail JSON shape changes incompatibly
- bump **trajectory export schema** (`TRAJECTORY_EXPORT_SCHEMA_VERSION`) when JSONL
  row shape changes incompatibly
- bump **trajectory projection**, **quality score**, or **Experience
  distillation** versions when their derived identity/formula changes; rebuild
  derived rows rather than migrating source evidence
- bump **semantic index format** when LanceDB projection or stored row fields change
  incompatibly — forces index rebuild, not SQLite migration (
  see [13-engineering-memory/index.md](13-engineering-memory/index.md))
- bump **Platform Observability schema** only for incompatible telemetry-store
  changes; it remains separate from reports, gates, baselines, and memory facts
  (see [26-platform-observability.md](26-platform-observability.md))
- bump **corpus analytics store/export/representation/embedding** versions when
  SQLite layout or export semantics change incompatibly; rebuild analytics
  artifacts rather than treating them as analysis truth (
  see [27-corpus-analytics.md](27-corpus-analytics.md))
    - store `1.1` adds migration-time orphan checks, relationship guards, and
      unique vector/display keys;
    - export `1.2` additively separates formal validity from interpretation,
      exposes full-versus-limited projection, bounded preview disclosure,
      partition metrics, and nullable all-run sweep comparison facts;
    - representation `3` retains raw representation-owned input hashing and
      materializes explicit trajectory, Patch Trail, and registry-overlay
      presence facts for new snapshots. Registry state remains outside source
      identity and existing contract-2 snapshots are not rewritten;
    - embedding `2` defines vector digests over canonical little-endian
      float32 bytes. Older embedding generations are rejected and must be
      regenerated.

Operational compatibility rules:

- runtime writes baseline schema `2.1`
- runtime accepts clone baseline `1.0`, `2.0`, and `2.1`
- runtime writes standalone metrics-baseline schema `1.2`
- runtime accepts standalone metrics-baseline `1.x` where the baseline minor
  version is less than or equal to the runtime minor (currently through `1.2`)
- runtime writes cache schema `2.8`
- MCP does not define a separate schema constant; tool/resource semantics are
  package-versioned public surface
- adding or changing an MCP tool is a package-versioned interface change and
  requires tests, docs, changelog, and tool-schema snapshot updates; it does not
  bump the canonical report schema unless report JSON changes

Baseline regeneration is required when:

- `fingerprint_version` changes
- `python_tag` changes

It is not required for package patch/minor updates when compatibility gates still pass.

## Health model evolution

CodeClone does not currently define a separate health-model version constant.
Health semantics are package-versioned behavior and must be documented in:

- this chapter
- [15-health-score.md](15-health-score.md)
- release notes

A lower score after upgrade may reflect a broader scoring model, not only worse code.

## Invariants (MUST)

- Contract changes require code + tests + changelog/docs updates.
- Schema mismatches map to explicit statuses.
- Legacy baselines stay untrusted and require regeneration.

Refs:

- `codeclone/baseline/trust.py:BaselineStatus`
- `codeclone/baseline/clone_baseline.py:_is_legacy_baseline_payload`

## Failure modes

| Change type                    | User impact                                                    |
|--------------------------------|----------------------------------------------------------------|
| Baseline schema bump           | Older unsupported baselines become untrusted until regenerated |
| Fingerprint bump               | Clone IDs change; baseline regeneration required               |
| Cache schema bump              | Old caches are ignored and rebuilt automatically               |
| Report schema bump             | Downstream report consumers must update                        |
| Metrics-baseline schema bump   | Dedicated metrics-baseline files must be regenerated           |
| Engineering Memory schema bump | Older DBs migrate or re-init per `schema_migrate.py`           |
| Semantic index format bump     | LanceDB sidecar invalidated; run `memory semantic rebuild`     |
| Platform Observability bump    | Local diagnostic store reader/writer must migrate together     |
| Corpus analytics store bump    | Writable open migrates supported stores; read-only open rejects stale schema |
| Corpus embedding contract bump | Existing generations must be regenerated before clustering     |

## Determinism / canonicalization

- Version constants are explicit and enforced in code.
- Compatibility decisions are runtime checks, not doc-only expectations.

Refs:

- `codeclone/contracts/__init__.py`
- `codeclone/baseline/clone_baseline.py:Baseline.verify_compatibility`
- `codeclone/baseline/metrics_baseline.py:MetricsBaseline.verify_compatibility`

## Locked by tests

- `tests/test_baseline.py::test_baseline_verify_schema_incompatibilities`
- `tests/test_baseline.py::test_baseline_verify_schema_incompatibilities[schema_major_mismatch]`
- `tests/test_baseline.py::test_baseline_verify_fingerprint_mismatch`
- `tests/test_cache.py::test_cache_v_field_version_mismatch_warns`
- `tests/test_report.py::test_report_json_compact_v21_contract`

## Non-guarantees

- Backward compatibility is not guaranteed across incompatible schema/fingerprint bumps.
- Health Score is not mathematically frozen forever; the obligation to document scoring-model changes is.
