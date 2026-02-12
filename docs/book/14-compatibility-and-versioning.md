# 14. Compatibility and Versioning

## Purpose
Define when to bump baseline/cache/report/fingerprint versions and what breaks.

## Public surface
- Version constants: `codeclone/contracts.py`
- Baseline compatibility checks: `codeclone/baseline.py:Baseline.verify_compatibility`
- Cache compatibility checks: `codeclone/cache.py:Cache._parse_cache_document`
- Report schema assignment: `codeclone/_report_serialize.py:to_json_report`

## Data model
Current contract versions:
- `BASELINE_SCHEMA_VERSION = "1.0"`
- `BASELINE_FINGERPRINT_VERSION = "1"`
- `CACHE_VERSION = "1.2"`
- `REPORT_SCHEMA_VERSION = "1.1"`

Refs:
- `codeclone/contracts.py`

## Contracts
Version bump rules:
- Bump **baseline schema** only for baseline JSON layout/type changes.
- Bump **fingerprint version** when detection semantics affecting function/block keys change.
- Bump **cache schema** for cache wire format changes.
- Bump **report schema** for JSON/TXT/HTML data contract changes.

Baseline regeneration rules:
- Required when `fingerprint_version` changes.
- Required when `python_tag` changes.
- Not required for package patch/minor changes alone if compatibility gates still pass.

Refs:
- `codeclone/baseline.py:Baseline.from_groups`
- `codeclone/cli.py:_main_impl`

## Invariants (MUST)
- Contract changes must include tests and changelog/docs updates.
- Schema mismatch must map to explicit statuses (not generic fallback).
- Legacy baseline layout is untrusted and requires explicit regeneration.

Refs:
- `codeclone/baseline.py:BaselineStatus`
- `codeclone/baseline.py:_is_legacy_baseline_payload`

## Failure modes
| Change type | User impact |
| --- | --- |
| Baseline schema bump | old baselines become untrusted until regenerated |
| Fingerprint bump | baseline diff keys change; regeneration required |
| Cache schema bump | old caches ignored and regenerated automatically |
| Report schema bump | downstream JSON/TXT consumers must update |

## Determinism / canonicalization
- Version constants are explicit and imported where enforced.
- Compatibility is code-driven, not documentation-driven.

Refs:
- `codeclone/contracts.py`
- `codeclone/baseline.py:Baseline.verify_compatibility`

## Locked by tests
- `tests/test_baseline.py::test_baseline_verify_schema_too_new`
- `tests/test_baseline.py::test_baseline_verify_fingerprint_mismatch`
- `tests/test_cache.py::test_cache_v_field_version_mismatch_warns`
- `tests/test_report.py::test_report_json_compact_v11_contract`

## Non-guarantees
- Backward compatibility is not promised across incompatible schema/fingerprint bumps.

## 1.5 architecture note
Planned for v1.5: architecture-layer review and module organization cleanup.
No planned change to clone-detection semantics or determinism contracts unless accompanied by explicit fingerprint/schema version bumps and tests.
