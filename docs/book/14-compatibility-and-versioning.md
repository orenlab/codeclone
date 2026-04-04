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
- `CACHE_VERSION = "2.3"`
- `REPORT_SCHEMA_VERSION = "2.3"`
- `METRICS_BASELINE_SCHEMA_VERSION = "1.0"` (used only when metrics are stored
  in a dedicated metrics-baseline file instead of the default unified baseline)

Refs:

- `codeclone/contracts.py`

## Contracts

Version bump rules:

- Bump **baseline schema** only for baseline JSON layout/type changes.
- Bump **fingerprint version** when clone key semantics change.
- Bump **cache schema** for cache wire-format/validation changes and for
  cached-analysis semantic changes that would otherwise leave stale cache
  entries looking compatible to runtime validation.
- Bump **report schema** for canonical report document contract changes
  (`report_schema_version`, consumed by JSON/TXT/Markdown/SARIF and HTML provenance/view).
- Bump **metrics-baseline schema** only for dedicated metrics-baseline payload
  changes.
- This schema does **not** imply that metrics normally live in a separate file:
  the default runtime path is still the unified baseline file, and the
  standalone metrics-baseline schema applies only when users opt into a
  different metrics-baseline path.
- MCP does not currently define a separate schema/version constant; tool names,
  resource shapes, and documented request/response semantics are therefore
  package-versioned public surface and must be documented/tested when changed.
- Slimming or splitting MCP-only projections (for example, summary payloads or
  `metrics` vs `metrics_detail`) does not change `report_schema_version` as long
  as the canonical report document and finding identities remain unchanged.
- The same rule applies to finding-level MCP projection changes such as
  short MCP ids, slim summary locations, or omitting `priority_factors`
  outside `detail_level="full"`.
- Additive MCP-only convenience fields/projections such as
  `cache.freshness` or production-first triage also do not change
  `report_schema_version` when they are derived from unchanged canonical report
  and summary data.
- The same rule applies to bounded MCP semantic guidance such as
  `help(topic=...)`: package-versioned wording and routing may evolve, but they
  do not change `report_schema_version` as long as canonical report semantics
  and finding identities remain unchanged.
- Canonical report changes such as `meta.analysis_thresholds.design_findings`
  or threshold-aware design finding materialization do change
  `report_schema_version` because they alter canonical report semantics and
  integrity payload.
- The same is true for additive canonical metrics families such as
  `metrics.families.overloaded_modules`: even though the layer is report-only and does
  not affect health/gates/findings, it still changes canonical report schema
  and integrity payload, so it requires a report-schema bump.
- CodeClone does not currently define a separate health-model version constant.
  Health-score semantics are package-versioned and must be documented in the
  Health Score chapter and release notes when they change.

Baseline compatibility rules:

- Runtime accepts baseline schema majors `1` and `2` with supported minors.
- Runtime writes current schema (`2.0`) on new/updated baseline saves.
- Embedded top-level `metrics` is valid only for baseline schema `>= 2.0`.

Baseline regeneration rules:

- Required when `fingerprint_version` changes.
- Required when `python_tag` changes.
- Not required for package patch/minor updates if compatibility gates still pass.

## Health model evolution

Health Score is stable within a given scoring model, but the scoring model may
evolve across releases.

New signal families may first appear as report-only or experimental layers.
After validation and contract hardening, selected layers may later be promoted
into scoring.

Future CodeClone releases may expand the Health Score formula with additional
validated signal families. As a result, a repository's score may decrease after
upgrade even if the code itself did not become worse. In such cases, the change
reflects an evolved scoring model rather than a retroactive decline in code
quality.

Short operational reminder:

> A lower score after upgrade may reflect a broader health model, not only
> worse code.

Contract consequence:

- health-model expansion does not necessarily require a baseline/cache/report
  schema bump;
- but it **does** require explicit documentation and release-note coverage,
  because it changes user-visible scoring semantics.

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
| Metrics-baseline schema bump | dedicated metrics-baseline files must be regenerated                  |

## Determinism / canonicalization

- Version constants are explicit and enforced in code.
- Compatibility decisions are runtime checks, not doc-only expectations.

Refs:

- `codeclone/contracts.py`
- `codeclone/baseline.py:Baseline.verify_compatibility`
- `codeclone/metrics_baseline.py:MetricsBaseline.verify_compatibility`

## Locked by tests

- `tests/test_baseline.py::test_baseline_verify_schema_incompatibilities[schema_too_new]`
- `tests/test_baseline.py::test_baseline_verify_schema_incompatibilities[schema_major_mismatch]`
- `tests/test_baseline.py::test_baseline_verify_fingerprint_mismatch`
- `tests/test_cache.py::test_cache_v_field_version_mismatch_warns`
- `tests/test_report.py::test_report_json_compact_v21_contract`

## Non-guarantees

- Backward compatibility is not guaranteed across incompatible schema/fingerprint
  bumps.
- Health Score is not frozen forever as a mathematical formula; what is frozen
  is the obligation to document scoring-model changes and present them honestly.
