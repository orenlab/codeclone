# 13. Testing as Specification

## Purpose

Map critical contracts to tests that lock behavior.

## Public surface

Contract tests are concentrated in:

- `tests/test_baseline.py`
- `tests/test_cache.py`
- `tests/test_report.py`
- `tests/test_cli_inprocess.py`
- `tests/test_cli_unit.py`
- `tests/test_html_report.py`
- `tests/test_detector_golden.py`
- `tests/test_golden_v2.py`

## Data model

Test classes by role:

- Unit contract tests (schema, validation, canonicalization)
- Integration contract tests (CLI mode behavior, exit-code priority)
- Golden detector snapshot (single canonical python tag)

## Contracts

The following matrix is treated as executable contract:

| Contract                                                                       | Tests                                                                                                         |
|--------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| Baseline schema/integrity/compat gates                                         | `tests/test_baseline.py`                                                                                      |
| Cache v2.3 fail-open + status mapping                                          | `tests/test_cache.py`, `tests/test_cli_inprocess.py::test_cli_reports_cache_too_large_respects_max_size_flag` |
| Exit code categories and markers                                               | `tests/test_cli_unit.py`, `tests/test_cli_inprocess.py`                                                       |
| Report schema v2.4 canonical/derived/integrity + JSON/TXT/MD/SARIF projections | `tests/test_report.py`, `tests/test_report_contract_coverage.py`, `tests/test_report_branch_invariants.py`    |
| HTML render-only explainability + escaping                                     | `tests/test_html_report.py`                                                                                   |
| Scanner traversal safety                                                       | `tests/test_scanner_extra.py`, `tests/test_security.py`                                                       |

## Invariants (MUST)

- Every schema/status contract change requires tests and docs update.
- Golden detector fixture is canonicalized to one Python tag.
- Untrusted baseline behavior must be tested for both normal and gating modes.
- V2 golden fixtures lock dead-code/test-path semantics, metrics/dependency aggregates,
  stable per-function structural fact surfaces (`stable_structure` /
  `cohort_structural_findings`), and CLI+`pyproject.toml` contract behavior.

Refs:

- `tests/test_detector_golden.py::test_detector_output_matches_golden_fixture`
- `tests/test_golden_v2.py::test_golden_v2_analysis_contracts`
- `tests/test_golden_v2.py::test_golden_v2_cli_pyproject_contract`
- `tests/test_cli_inprocess.py::test_cli_legacy_baseline_normal_mode_ignored_and_exit_zero`
- `tests/test_cli_inprocess.py::test_cli_legacy_baseline_fail_on_new_fails_fast_exit_2`

## Failure modes

| Condition                       | Expected test signal                    |
|---------------------------------|-----------------------------------------|
| Baseline payload contract drift | baseline integrity/canonical tests fail |
| Cache schema drift              | cache version/parse tests fail          |
| Report schema drift             | compact layout tests fail               |
| Exit priority drift             | CI inprocess tests fail                 |

## Determinism / canonicalization

- Determinism tests compare ordering and stable payloads, not runtime-specific timestamps.

## Locked by tests

- `tests/test_baseline.py::test_baseline_payload_fields_contract_invariant`
- `tests/test_cache.py::test_cache_v13_missing_optional_sections_default_empty`
- `tests/test_report.py::test_report_json_compact_v21_contract`
- `tests/test_cli_inprocess.py::test_cli_contract_error_priority_over_gating_failure_for_unreadable_source`
- `tests/test_html_report.py::test_html_and_json_group_order_consistent`
- `tests/test_detector_golden.py::test_detector_output_matches_golden_fixture`
- `tests/test_golden_v2.py::test_golden_v2_analysis_contracts`
- `tests/test_golden_v2.py::test_golden_v2_cli_pyproject_contract`
- `tests/test_extractor.py::test_extract_collects_referenced_qualnames_for_import_aliases`
- `tests/test_extractor.py::test_collect_dead_candidates_skips_protocol_and_stub_like_symbols`
- `tests/test_metrics_modules.py::test_find_unused_respects_referenced_qualnames`

## Non-guarantees

- Test implementation details (fixtures/helper names) can change if contract assertions remain equivalent.
