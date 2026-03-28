# 14. Compatibility and Versioning

## Purpose

Define when to bump baseline/cache/report/fingerprint versions and how runtime
compatibility is enforced.

## Public surface

- Version constants: `codeclone/contracts.py`
- Baseline compatibility checks: `codeclone/baseline.py:Baseline.verify_compatibility`
- Metrics baseline compatibility checks: `codeclone/metrics_baseline.py:MetricsBaseline.verify_compatibility`
- Cache compatibility checks: `codeclone/cache.py:Cache.load`
- Report schema assignment: `codeclone/report/json_contract.py:build_report_document`
- MCP public surface: `codeclone/mcp_server.py`, `codeclone/mcp_service.py`

## Data model

Current contract versions:

- `BASELINE_SCHEMA_VERSION = "2.0"`
- `BASELINE_FINGERPRINT_VERSION = "1"`
- `CACHE_VERSION = "2.2"`
- `REPORT_SCHEMA_VERSION = "2.1"`
- `METRICS_BASELINE_SCHEMA_VERSION = "1.0"` (standalone metrics-baseline file)

Refs:

- `codeclone/contracts.py`

## Contracts

Version bump rules:

- Bump **baseline schema** only for baseline JSON layout/type changes.
- Bump **fingerprint version** when clone key semantics change.
- Bump **cache schema** for cache wire-format/validation changes.
- Bump **report schema** for canonical report document contract changes
  (`report_schema_version`, consumed by JSON/TXT/Markdown/SARIF and HTML provenance/view).
- Bump **metrics-baseline schema** only for standalone metrics-baseline payload changes.
- MCP does not currently define a separate schema/version constant; tool names,
  resource shapes, and documented request/response semantics are therefore
  package-versioned public surface and must be documented/tested when changed.

Baseline compatibility rules:

- Runtime accepts baseline schema majors `1` and `2` with supported minors.
- Runtime writes current schema (`2.0`) on new/updated baseline saves.
- Embedded top-level `metrics` is valid only for baseline schema `>= 2.0`.

Baseline regeneration rules:

- Required when `fingerprint_version` changes.
- Required when `python_tag` changes.
- Not required for package patch/minor updates if compatibility gates still pass.

## Invariants (MUST)

- Contract changes must include code updates and changelog/docs updates.
- Schema mismatches must map to explicit statuses.
- Legacy baseline payloads (<=1.3 layout) remain untrusted and require regeneration.

Refs:

- `codeclone/baseline.py:BaselineStatus`
- `codeclone/baseline.py:_is_legacy_baseline_payload`

## Failure modes

| Change type                  | User impact                                                           |
|------------------------------|-----------------------------------------------------------------------|
| Baseline schema bump         | older unsupported baseline schemas become untrusted until regenerated |
| Fingerprint bump             | clone IDs change; baseline regeneration required                      |
| Cache schema bump            | old caches are ignored and rebuilt automatically                      |
| Report schema bump           | downstream report consumers must update                               |
| Metrics-baseline schema bump | standalone metrics baseline must be regenerated                       |

## Determinism / canonicalization

- Version constants are explicit and enforced in code.
- Compatibility decisions are runtime checks, not doc-only expectations.

Refs:

- `codeclone/contracts.py`
- `codeclone/baseline.py:Baseline.verify_compatibility`
- `codeclone/metrics_baseline.py:MetricsBaseline.verify_compatibility`

## Locked by tests

- `tests/test_baseline.py::test_baseline_verify_schema_too_new`
- `tests/test_baseline.py::test_baseline_verify_schema_major_mismatch`
- `tests/test_baseline.py::test_baseline_verify_fingerprint_mismatch`
- `tests/test_cache.py::test_cache_v_field_version_mismatch_warns`
- `tests/test_report.py::test_report_json_compact_v21_contract`

## Non-guarantees

- Backward compatibility is not guaranteed across incompatible schema/fingerprint
  bumps.
