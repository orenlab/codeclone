<!-- doc-scope: TESTS AS SPECIFICATION.
     owns: testing philosophy, test taxonomy, golden/snapshot policy, contract matrix.
     does-not-own: per-file test inventory (→ test modules), maintainer playbook detail
       (→ AGENTS.md §17, mirrored here). -->
# 23. Testing as Specification

## Purpose

Map critical contracts to tests that lock behavior.

## Public surface

Contract tests are concentrated in:

- `tests/test_baseline.py`
- `tests/test_cache.py`
- `tests/test_report.py`
- `tests/test_report_contract_coverage.py`
- `tests/test_cli_inprocess.py`
- `tests/test_cli_unit.py`
- `tests/test_coverage_join.py`
- `tests/test_golden_fixtures.py`
- `tests/test_html_report.py`
- `tests/test_mcp_service.py`
- `tests/test_detector_golden.py`
- `tests/test_golden_v2.py`
- `tests/test_memory_*.py`, `tests/test_semantic_*.py`, `tests/test_mcp_memory_management.py`
- `tests/test_memory_trajectory_*.py`, `tests/test_memory_experience_*.py`
- `tests/test_memory_projection_jobs*.py`
- `tests/test_observability_*.py`
- `tests/test_docs_ia_contract.py`, `tests/test_docs_build_contract.py`
- `tests/test_architecture.py`

## Test taxonomy

Treat tests as specification. Every new behavior belongs in the closest bucket;
public-surface changes need contract tests, not only unit tests.

| Bucket | Intent | Examples |
|--------|--------|----------|
| **Unit** | Module behavior and edge conditions | `tests/test_cfg.py`, `tests/test_normalize.py`, `tests/test_metrics_modules.py`, `tests/test_suppressions.py` |
| **Contract** | Baseline, cache, report, CLI, MCP public semantics | `tests/test_baseline.py`, `tests/test_cache.py`, `tests/test_report_contract_coverage.py`, `tests/test_cli_unit.py`, `tests/test_mcp_service.py` |
| **Golden** | Snapshot sentinels for stable outputs | `tests/test_detector_golden.py`, `tests/test_golden_v2.py` |
| **Determinism / invariant** | Ordering, branch paths, canonical stability | `tests/test_report_branch_invariants.py`, `tests/test_core_branch_coverage.py`, `tests/test_semantic_determinism_gate.py` |
| **Scenario / regression** | Multi-step integration and process behavior | `tests/test_cli_inprocess.py`, `tests/test_pipeline_process.py`, `tests/test_cli_smoke.py` |

Maintainer routing tables and golden-update policy also live in `AGENTS.md` §17
and §16 (change routing); this chapter is the published contract copy.

## Contracts

The following matrix is treated as executable contract:

| Contract                                                                                                                                               | Tests                                                                                                                                                                                                                                                                                     |
|--------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Baseline schema/integrity/compat gates                                                                                                                 | `tests/test_baseline.py`                                                                                                                                                                                                                                                                  |
| Cache v2.8 fail-open + status mapping + API-surface-aware reuse + runtime-reachability/security-surface persistence + API signature order preservation | `tests/test_cache.py`, `tests/test_cli_inprocess.py::test_cli_reports_cache_too_large_respects_max_size_flag`, `tests/test_cli_inprocess.py::test_cli_public_api_breaking_count_stable_across_warm_cache`, `tests/test_cli_inprocess.py::test_cli_api_surface_ignores_non_api_warm_cache` |
| Exit code categories and markers                                                                                                                       | `tests/test_cli_unit.py`, `tests/test_cli_inprocess.py`                                                                                                                                                                                                                                   |
| Report schema v2.11 canonical/derived/integrity + JSON/TXT/MD/SARIF projections                                                                        | `tests/test_report.py`, `tests/test_report_contract_coverage.py`, `tests/test_report_branch_invariants.py`                                                                                                                                                                                |
| HTML render-only explainability + escaping                                                                                                             | `tests/test_html_report.py`                                                                                                                                                                                                                                                               |
| Current-run Cobertura coverage join parsing, gating, and projections                                                                                   | `tests/test_coverage_join.py`, `tests/test_pipeline_metrics.py`, `tests/test_cli_unit.py`, `tests/test_mcp_service.py`, `tests/test_html_report.py`                                                                                                                                       |
| Report-only security surfaces inventory and projections                                                                                                | `tests/test_security_surfaces.py`, `tests/test_pipeline_metrics.py`, `tests/test_cache.py`, `tests/test_report_contract_coverage.py`, `tests/test_cli_unit.py`, `tests/test_html_report.py`, `tests/test_mcp_service.py`, `tests/test_mcp_server.py`                                      |
| Framework-aware dead-code reachability facts                                                                                                           | `tests/test_extractor.py`, `tests/test_pipeline_metrics.py`, `tests/test_cache.py`                                                                                                                                                                                                        |
| Golden fixture clone exclusion policy                                                                                                                  | `tests/test_golden_fixtures.py`, `tests/test_cli_inprocess.py::test_cli_pyproject_golden_fixture_paths_exclude_fixture_clone_groups`, `tests/test_report.py::test_report_json_clone_groups_can_include_suppressed_golden_fixture_bucket`                                                  |
| Scanner traversal safety                                                                                                                               | `tests/test_scanner_extra.py`, `tests/test_security.py`                                                                                                                                                                                                                                   |
| Engineering Memory SQLite schema, governance, retrieval                                                                                                  | `tests/test_memory_schema.py`, `tests/test_memory_store.py`, `tests/test_memory_governance.py`, `tests/test_memory_retrieval.py`, `tests/test_memory_mcp_sync.py`                                                                                                                         |
| Semantic index projection, rebuild, LanceDB backend                                                                                                      | `tests/test_semantic_projection.py`, `tests/test_semantic_rebuild.py`, `tests/test_semantic_lancedb_backend.py`, `tests/test_semantic_embedding.py`                                                                                                                                       |
| Trajectory projection, quality passport, anomalies, retrieval                                                                                            | `tests/test_memory_trajectory_projector.py`, `tests/test_memory_trajectory_quality.py`, `tests/test_memory_trajectory_anomalies.py`, `tests/test_memory_trajectory_retrieval.py`                                                                                                          |
| Experience distillation, evidence diversity, scoped retrieval, promotion                                                                                  | `tests/test_memory_experience_distillation.py`, `tests/test_memory_experience_retrieval.py`, `tests/test_memory_experience_promotion.py`                                                                                                                                                  |
| Projection queue coalescing, watermarks, worker lifecycle                                                                                                 | `tests/test_memory_projection_jobs.py`, `tests/test_memory_projection_jobs_schema.py`, `tests/test_projection_spawn_guard.py`                                                                                                                                                            |
| Platform Observability config, correlation, persistence, query, rendering, MCP                                                                            | `tests/test_observability_config.py`, `tests/test_observability_correlation.py`, `tests/test_observability_store.py`, `tests/test_observability_query.py`, `tests/test_observability_render.py`, `tests/test_observability_mcp_registrar.py`                                                                                          |
| Documentation IA, line budgets, strict site build                                                                                                          | `tests/test_docs_ia_contract.py`, `tests/test_docs_build_contract.py`                                                                                                                                                                                                                     |
| Layer dependency direction                                                                                                                             | `tests/test_architecture.py`                                                                                                                                                                                                                                                              |

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
- `tests/test_coverage_join.py::test_build_coverage_join_maps_cobertura_lines_to_function_spans`
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
