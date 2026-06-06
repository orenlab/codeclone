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
- `ENGINEERING_MEMORY_SCHEMA_VERSION = "1.4"`
- `PATCH_TRAIL_SCHEMA_VERSION = "1"` (finish-time Patch Trail JSON; audit + SQLite sidecar)
- `TRAJECTORY_EXPORT_SCHEMA_VERSION = "2"` (JSONL export rows; `codeclone/memory/trajectory/profiles.py`)
- `SEMANTIC_INDEX_FORMAT_VERSION = "1"` (LanceDB sidecar; separate from SQLite memory schema)

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
  (`codeclone/memory/schema_migrate.py`) — e.g. **`1.4`** adds
  `memory_trajectory_patch_trails`
- bump **patch trail schema** (`PATCH_TRAIL_SCHEMA_VERSION`) when finish-time Patch
  Trail JSON shape changes incompatibly
- bump **trajectory export schema** (`TRAJECTORY_EXPORT_SCHEMA_VERSION`) when JSONL
  row shape changes incompatibly
- bump **semantic index format** when LanceDB projection or stored row fields change
  incompatibly — forces index rebuild, not SQLite migration (see [13-engineering-memory.md](13-engineering-memory.md))

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
