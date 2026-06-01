# 16. Dead Code Contract

## Purpose

Define dead-code liveness rules, canonical symbol-usage boundaries, and gating semantics.

## Public surface

- Dead-code detection core: `codeclone/metrics/dead_code.py:find_unused`
- Test-path classifier: `codeclone/paths/__init__.py:is_test_filepath`
- Inline suppression parser/binder: `codeclone/analysis/suppressions.py`
- Extraction of referenced names/candidates:
  `codeclone/analysis/units.py:extract_units_and_stats_from_source`
- Cache load boundary for referenced names:
  `codeclone/core/discovery_cache.py:load_cached_metrics_extended`
- Package entry-point liveness:
  `codeclone/core/entrypoints.py:collect_project_entrypoint_qualnames`

## Data model

- Candidate model: `DeadCandidate`
- Output model: `DeadItem` (`confidence=high|medium`)
- Runtime reachability evidence: `RuntimeReachabilityFact`
- Global liveness input:
    - `referenced_names: frozenset[str]`
    - `referenced_qualnames: frozenset[str]`
    - `runtime_reachability: tuple[RuntimeReachabilityFact, ...]`

Refs:

- `codeclone/models.py:DeadCandidate`
- `codeclone/models.py:DeadItem`
- `codeclone/models.py:RuntimeReachabilityFact`

## Contracts

- References from test files are excluded from liveness accounting.
- Symbols declared in test files are non-actionable and filtered.
- Symbols with names matching test entrypoint conventions are filtered:
  `test_*`, `pytest_*`.
- Methods are filtered as non-actionable when dynamic/runtime dispatch is
  expected:
  dunder methods, `visit_*`, setup/teardown hooks.
- Module-level PEP 562 hooks are filtered as non-actionable:
  `__getattr__`, `__dir__`.
- Declaration-level inline suppression is supported with:
  `# codeclone: ignore[dead-code]` (leading or inline comment form).
- For multiline declaration headers, inline suppression may appear either on the
  first declaration line or on the closing header line containing `:`.
- Suppression is declaration-scoped (`def`, `async def`, `class`) and does not
  implicitly propagate to unrelated declaration targets.
- Candidate extraction excludes non-runtime declaration surfaces:
  `Protocol` classes, methods on `Protocol` classes, and callables decorated with
  `@overload` / `@abstractmethod`.
- Candidate extraction also excludes exact Pydantic runtime hooks when their
  decorators are resolved from `pydantic` / `pydantic.v1` imports or module
  aliases: validators, model/field validators, serializers, and computed fields.
- A symbol referenced by exact canonical qualname is not dead.
- A symbol referenced by local name is not dead.
- A top-level symbol listed in a literal `__all__` export is not dead. This is
  resolved to exact module-level function/class qualnames and does not mark
  same-named methods live.
- A symbol re-exported through a literal `__all__` entry and an exact
  `from module import Symbol` binding is resolved back to the imported
  canonical qualname.
- A symbol exposed through a PEP 562 lazy-export module is resolved when the
  module has a module-level `__getattr__`, a literal `_EXPORTS` mapping, and a
  matching literal `__all__` entry. Dynamic or non-literal export maps are not
  interpreted.
- A symbol referenced by package metadata entry points is not dead when
  `[project.scripts]`, `[project.gui-scripts]`, `[project.entry-points.*]`, or
  `[tool.poetry.scripts]` resolves to an exact known candidate qualname. Unique
  suffix matches are allowed only for common `src.<package>` style layouts;
  ambiguous matches are ignored.
- A symbol referenced only by qualified-name suffix (without canonical module
  match) downgrades confidence to `medium`.
- A method name observed through guarded dynamic lookup is treated as a
  referenced local name only when the same callable scope contains all three
  pieces of evidence: `getattr(obj, "method", ...)`, `callable(local)` guard,
  and a subsequent call through that same local binding.
- Runtime framework registration facts can mark a symbol live when the extractor
  observes a deterministic edge from modern Python runtime surfaces:
  FastAPI/Starlette route and dependency registration, including
  typed route decorator factories, `Annotated[..., Depends(...)]` and
  `Annotated[..., Security(...)]` route parameters, Starlette
  `BaseHTTPMiddleware.dispatch` hooks, Aiogram router observer decorators,
  Flask/Blueprint routes, aiohttp `RouteTableDef` decorators, Django URL
  patterns, Dependency Injector providers, Typer/Click commands, Celery tasks,
  and SQLAlchemy `TypeDecorator` runtime hooks.
- Runtime reachability facts are evidence, not a full call graph. High- and
  medium-confidence facts prevent false dead-code findings; low-confidence
  facts, if introduced later, must remain report-only until explicitly wired.
- `--fail-dead-code` gate counts only high-confidence dead-code items.
- Suppressed dead-code candidates are excluded from active dead-code findings
  and from health-score dead-code penalties.
- Suppressed dead-code candidates are surfaced separately in report metrics
  (`dead_code.summary.suppressed`, `dead_code.suppressed_items`) and in the
  HTML dead-code split view (`Active` / `Suppressed`).

Refs:

- `codeclone/metrics/dead_code.py:_is_non_actionable_candidate`
- `codeclone/metrics/dead_code.py:find_unused`
- `codeclone/analysis/reachability.py:collect_runtime_reachability`
- `codeclone/report/gates/evaluator.py:metric_gate_reasons`

## Invariants (MUST)

- Output dead-code items are deterministically sorted by
  `(filepath, start_line, end_line, qualname, kind)`.
- Test-path suppression is applied both on fresh extraction and cached-metrics
  load for both `referenced_names` and `referenced_qualnames`.
- Runtime reachability facts are collected during AST extraction, cached with
  the file metrics payload, and reused on warm runs so dead-code behavior is
  identical for cold and cached analysis.
- Package entry-point liveness is a project-level pass over `pyproject.toml` and
  is not stored in per-file cache entries.

Refs:

- `codeclone/metrics/dead_code.py:find_unused`
- `codeclone/analysis/units.py:extract_units_and_stats_from_source`
- `codeclone/core/discovery_cache.py:load_cached_metrics_extended`

## Failure modes

| Condition                                          | Behavior                                  |
|----------------------------------------------------|-------------------------------------------|
| Dynamic method pattern (dunder/visitor/setup hook) | Candidate skipped as non-actionable       |
| Module PEP 562 hook (`__getattr__`/`__dir__`)      | Candidate skipped as non-actionable       |
| Malformed/unknown `# codeclone: ignore[...]` rule  | Ignored safely                            |
| Protocol or stub-like declaration surface          | Candidate skipped as non-actionable       |
| Definition appears only in tests                   | Candidate skipped                         |
| Symbol used only from tests                        | Remains actionable dead-code candidate    |
| Symbol used through import alias / module alias    | Matched via canonical qualname usage      |
| Symbol exported through literal `__all__`          | Matched via exact module-level qualname   |
| Symbol re-exported through literal `__all__`       | Matched via exact imported qualname       |
| Symbol exposed through literal lazy `_EXPORTS`     | Matched via exact lazy-export qualname    |
| Symbol exposed through package entry point         | Matched via exact/unique project qualname |
| Guarded `getattr(obj, "method")` callable dispatch | Method name becomes runtime reference     |
| Symbol registered through a supported runtime edge | Candidate skipped as runtime-reachable    |
| `--fail-dead-code` with high-confidence dead items | Gating failure, exit `3`                  |

## Determinism / canonicalization

- Filtering rules are deterministic string/path predicates.
- Runtime reachability is based on exact AST evidence for known framework
  contracts; it does not execute imports or inspect installed packages.
- Framework-specific non-runtime hooks are import/alias-resolved; CodeClone does
  not suppress arbitrary same-named local decorators.
- Package entry-point liveness reads only local project metadata and ignores
  invalid, dynamic, or ambiguous entry-point references.
- Lazy export and guarded dynamic `getattr` handling require literal AST
  evidence and same-scope call evidence; CodeClone does not execute import
  hooks or infer arbitrary dynamic dispatch.
- Candidate and result ordering is deterministic.

Refs:

- `codeclone/paths/__init__.py:is_test_filepath`
- `codeclone/metrics/dead_code.py:_is_dunder`
- `codeclone/metrics/dead_code.py:find_unused`

## Locked by tests

- `tests/test_extractor.py::test_dead_code_marks_symbol_dead_when_referenced_only_by_tests`
- `tests/test_extractor.py::test_dead_code_respects_runtime_hooks_and_inline_suppressions[skip_pep562_hooks]`
-
`tests/test_extractor.py::test_dead_code_respects_runtime_hooks_and_inline_suppressions[inline_suppression_per_declaration]`
-
`tests/test_extractor.py::test_dead_code_respects_runtime_hooks_and_inline_suppressions[suppression_binding_scoped_to_target]`
- `tests/test_extractor.py::test_dead_code_uses_fastapi_route_and_dependency_reachability`
- `tests/test_extractor.py::test_dead_code_uses_fastapi_annotated_dependency_reachability`
- `tests/test_extractor.py::test_dead_code_uses_fastapi_route_decorator_factory_reachability`
- `tests/test_extractor.py::test_dead_code_uses_aiogram_router_observer_reachability`
- `tests/test_extractor.py::test_dead_code_uses_flask_and_aiohttp_route_reachability`
- `tests/test_extractor.py::test_dead_code_uses_starlette_base_http_middleware_dispatch_hook`
- `tests/test_extractor.py::test_dead_code_uses_sqlalchemy_type_decorator_runtime_hooks`
- `tests/test_extractor.py::test_dead_code_uses_django_urlpattern_reachability`
- `tests/test_extractor.py::test_dead_code_uses_dependency_injector_provider_reachability`
- `tests/test_extractor.py::test_dead_code_uses_cli_and_task_registration_reachability`
- `tests/test_extractor.py::test_extract_collects_referenced_qualnames_for_import_aliases`
- `tests/test_extractor.py::test_extract_collects_referenced_qualnames_for_module_all_exports`
- `tests/test_extractor.py::test_extract_resolves_public_reexports_to_source_symbols`
- `tests/test_extractor.py::test_extract_treats_guarded_dynamic_getattr_call_as_runtime_reference`
- `tests/test_extractor.py::test_extract_ignores_uncalled_dynamic_getattr_probe`
- `tests/test_extractor.py::test_collect_dead_candidates_skips_protocol_and_stub_like_symbols`
- `tests/test_extractor.py::test_collect_dead_candidates_skips_pydantic_hooks_and_dataclass_post_init`
- `tests/test_core_branch_coverage.py::test_project_entrypoints_mark_exact_and_unique_layout_symbols_live`
- `tests/test_core_branch_coverage.py::test_pipeline_analyze_uses_project_entrypoints_for_dead_code`
- `tests/test_pipeline_metrics.py::test_load_cached_metrics_ignores_referenced_names_from_test_files`
- `tests/test_metrics_modules.py::test_find_unused_filters_non_actionable_and_preserves_ordering`
- `tests/test_metrics_modules.py::test_find_unused_respects_referenced_qualnames`
- `tests/test_metrics_modules.py::test_find_unused_keeps_non_pep562_module_dunders_actionable`
- `tests/test_metrics_modules.py::test_find_unused_applies_inline_dead_code_suppression`
- `tests/test_metrics_modules.py::test_find_suppressed_unused_returns_actionable_suppressed_candidates`
- `tests/test_report.py::test_report_json_dead_code_suppressed_items_are_reported_separately`
- `tests/test_html_report.py::test_html_report_renders_dead_code_split_with_suppressed_layer`
- `tests/test_suppressions.py::test_extract_suppression_directives_supports_inline_and_leading_forms`
- `tests/test_suppressions.py::test_bind_suppressions_targets_expected_declaration_scope[adjacent_leading_only]`

## Non-guarantees

- No full runtime call-graph, points-to, or framework container execution is
  performed.
- Unsupported frameworks may still need explicit
  `# codeclone: ignore[dead-code]` suppressions until their registration
  contracts are modeled.
- Medium-confidence dead items are informational and not used by
  `--fail-dead-code` gating.

## See also

- [05-core-pipeline.md](05-core-pipeline.md)
- [09-cli.md](09-cli.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
