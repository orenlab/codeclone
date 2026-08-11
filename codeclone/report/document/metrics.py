# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ...analysis.suppressions import INLINE_CODECLONE_SUPPRESSION_SOURCE
from ...domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    FAMILY_DEAD_CODE,
)
from ...domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    RISK_LOW,
)
from ...domain.source_scope import (
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_ORDER,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from ...metrics.registry import METRIC_FAMILIES
from ...paths import classify_source_kind as _classify_source_kind
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..derived import normalized_source_kind as _normalized_source_kind
from ._common import (
    _CONFIDENCE_RANK,
    _contract_path,
    _normalize_nested_string_rows,
    _operational_sort_key,
    _optional_str,
    health_verdict_withheld,
)

_OVERLOADED_MODULES_FAMILY = "overloaded_modules"

_COVERAGE_ADOPTION_FAMILY = "coverage_adoption"

_API_SURFACE_FAMILY = "api_surface"

_COVERAGE_JOIN_FAMILY = "coverage_join"

_SECURITY_SURFACES_FAMILY = "security_surfaces"

_SEMANTIC_AUTHORITY_FAMILY = "semantic_authority"


def _producer_source_kind(producers: Sequence[str]) -> str:
    """Classify a candidate group by its most production-facing producer.

    Producers are qualnames whose module prefix is a dotted path or a file
    path, so the prefix classifies exactly like the file it names. A group is
    ranked by its strongest member: a candidate that touches production code is
    worth reading before a pair of test twins, and combining the members into
    "mixed" instead would rank it below both.
    """

    kinds = set()
    for producer in producers:
        module, _separator, _local = str(producer).partition(":")
        if not module.strip():
            continue
        kinds.add(_classify_source_kind(module.replace(".", "/")))
    if not kinds:
        return SOURCE_KIND_OTHER
    return min(
        kinds,
        key=lambda kind: SOURCE_KIND_ORDER.get(kind, len(SOURCE_KIND_ORDER)),
    )


def _cycle_kind_count(
    cycle_details: Sequence[Mapping[str, object]],
    *,
    kind: str,
    cycles_total: int,
) -> int:
    """Count cycles of one kind, defaulting an unclassified run to import.

    Mirrors the metrics-layer fallback deliberately: when details do not align
    with the cycle list the classification was never recorded, and the only
    safe reading of an unclassified cycle is the critical one. Returning zero
    import cycles there would hand the gate a clean verdict it never earned.
    """

    if len(cycle_details) != cycles_total:
        return cycles_total if kind == "import_cycle" else 0
    return sum(1 for detail in cycle_details if detail.get("kind") == kind)


def _normalize_metrics_families(
    metrics: Mapping[str, object] | None,
    *,
    scan_root: str,
) -> dict[str, object]:
    metrics_map = _as_mapping(metrics)
    complexity = _as_mapping(metrics_map.get(CATEGORY_COMPLEXITY))
    complexity_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "cyclomatic_complexity": _as_int(
                    item_map.get("cyclomatic_complexity"),
                    1,
                ),
                # Diagnostic companion; never the sort key and never a gate.
                "cfg_cyclomatic_complexity": _as_int(
                    item_map.get("cfg_cyclomatic_complexity"),
                    1,
                ),
                "nesting_depth": _as_int(item_map.get("nesting_depth")),
                "risk": str(item_map.get("risk", RISK_LOW)),
            }
            for item in _as_sequence(complexity.get("functions"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: _operational_sort_key(
            item, metric_field="cyclomatic_complexity"
        ),
    )

    coupling = _as_mapping(metrics_map.get(CATEGORY_COUPLING))
    coupling_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "cbo": _as_int(item_map.get("cbo")),
                "risk": str(item_map.get("risk", RISK_LOW)),
                "coupled_classes": sorted(
                    {
                        str(name)
                        for name in _as_sequence(item_map.get("coupled_classes"))
                        if str(name).strip()
                    }
                ),
            }
            for item in _as_sequence(coupling.get("classes"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: _operational_sort_key(item, metric_field="cbo"),
    )

    cohesion = _as_mapping(metrics_map.get(CATEGORY_COHESION))
    cohesion_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "lcom4": _as_int(item_map.get("lcom4")),
                "risk": str(item_map.get("risk", RISK_LOW)),
                "method_count": _as_int(item_map.get("method_count")),
                "instance_var_count": _as_int(item_map.get("instance_var_count")),
            }
            for item in _as_sequence(cohesion.get("classes"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: _operational_sort_key(item, metric_field="lcom4"),
    )

    dependencies = _as_mapping(metrics_map.get("dependencies"))
    dependencies_comparison = _as_mapping(dependencies.get("summary"))
    dependency_edges = sorted(
        (
            {
                "source": str(item_map.get("source", "")),
                "target": str(item_map.get("target", "")),
                "import_type": str(item_map.get("import_type", "")),
                "line": _as_int(item_map.get("line")),
                "binding": str(item_map.get("binding", "import_time")),
                "is_lazy": bool(item_map.get("is_lazy", False)),
            }
            for item in _as_sequence(dependencies.get("edge_list"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["source"],
            item["target"],
            item["import_type"],
            item["line"],
        ),
    )
    # Sites where a dynamic load kept an opaque argument resolve to no target,
    # so they can never appear as an import edge. Carrying them as their own
    # section keeps the frontier's under-approximation visible to every
    # consumer from one key, instead of each surface rediscovering it.
    dynamic_boundaries = sorted(
        (
            {
                "source": dict(_as_mapping(observation.get("source"))),
                "syntax_kind": str(observation.get("syntax_kind", "")),
                "reason": "dynamic_load_argument_opaque",
            }
            for raw in _as_sequence(dependencies.get("observations"))
            for observation in (_as_mapping(raw),)
            if str(observation.get("resolution", "")).strip() == "unresolved_dynamic"
        ),
        key=lambda row: (
            str(_as_mapping(_as_mapping(row["source"]).get("file")).get("path", "")),
            str(row["syntax_kind"]),
        ),
    )
    dependency_cycles = _normalize_nested_string_rows(dependencies.get("cycles"))
    dependency_cycle_details = [
        {
            "modules": [
                str(module) for module in _as_sequence(detail_map.get("modules"))
            ],
            "kind": str(detail_map.get("kind", "import_cycle")),
            "member_paths": [
                str(path) if path is not None else None
                for path in _as_sequence(detail_map.get("member_paths"))
            ],
        }
        for detail in _as_sequence(dependencies.get("cycle_details"))
        for detail_map in (_as_mapping(detail),)
    ]
    longest_chains = _normalize_nested_string_rows(dependencies.get("longest_chains"))

    dead_code = _as_mapping(metrics_map.get(FAMILY_DEAD_CODE))

    def _normalize_suppressed_by(
        raw_bindings: object,
    ) -> list[dict[str, str]]:
        normalized_bindings = sorted(
            {
                (
                    str(binding_map.get("rule", "")).strip(),
                    str(binding_map.get("source", "")).strip(),
                )
                for binding in _as_sequence(raw_bindings)
                for binding_map in (_as_mapping(binding),)
                if str(binding_map.get("rule", "")).strip()
            },
            key=lambda item: (item[0], item[1]),
        )
        if not normalized_bindings:
            return []
        return [
            {
                "rule": rule,
                "source": source or INLINE_CODECLONE_SUPPRESSION_SOURCE,
            }
            for rule, source in normalized_bindings
        ]

    dead_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "kind": str(item_map.get("kind", "")),
                "confidence": str(item_map.get("confidence", CONFIDENCE_MEDIUM)),
                "reason": str(item_map.get("reason", "unreferenced")),
                "test_reference_sources": sorted(
                    {
                        str(source)
                        for source in _as_sequence(
                            item_map.get("test_reference_sources")
                        )
                        if str(source)
                    }
                ),
            }
            for item in _as_sequence(dead_code.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: _operational_sort_key(
            item,
            rank_field="confidence",
            rank_vocabulary=_CONFIDENCE_RANK,
        ),
    )
    dead_suppressed_items = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "kind": str(item_map.get("kind", "")),
                "confidence": str(item_map.get("confidence", CONFIDENCE_MEDIUM)),
                "reason": str(item_map.get("reason", "unreferenced")),
                "test_reference_sources": sorted(
                    {
                        str(source)
                        for source in _as_sequence(
                            item_map.get("test_reference_sources")
                        )
                        if str(source)
                    }
                ),
                "suppressed_by": _normalize_suppressed_by(
                    item_map.get("suppressed_by")
                ),
            }
            for item in _as_sequence(dead_code.get("suppressed_items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["kind"],
            item["confidence"],
            tuple(
                (
                    str(_as_mapping(binding).get("rule", "")),
                    str(_as_mapping(binding).get("source", "")),
                )
                for binding in _as_sequence(item.get("suppressed_by"))
            ),
        ),
    )
    for item in dead_suppressed_items:
        suppressed_by = _as_sequence(item.get("suppressed_by"))
        first_binding = _as_mapping(suppressed_by[0]) if suppressed_by else {}
        item["suppression_rule"] = str(first_binding.get("rule", ""))
        item["suppression_source"] = str(first_binding.get("source", ""))

    dead_unreachable_statements = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "reason": str(item_map.get("reason", "unreachable_block")),
                "statement_count": _as_int(item_map.get("statement_count")),
                "confidence": str(item_map.get("confidence", CONFIDENCE_HIGH)),
            }
            for item in _as_sequence(dead_code.get("unreachable_statements"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["reason"],
        ),
    )

    dead_unresolved_overrides = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "kind": str(item_map.get("kind", "")),
                "class_qualname": str(item_map.get("class_qualname", "")),
                "base_names": sorted(
                    {
                        str(base)
                        for base in _as_sequence(item_map.get("base_names"))
                        if str(base)
                    }
                ),
                "reason": str(item_map.get("reason", "unresolved_external_base")),
            }
            for item in _as_sequence(dead_code.get("unresolved_overrides"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
        ),
    )
    dead_live_root_reasons = sorted(
        (
            {
                "qualname": str(item_map.get("qualname", "")),
                "reason": str(item_map.get("reason", "")),
            }
            for item in _as_sequence(dead_code.get("live_root_reasons"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (item["qualname"], item["reason"]),
    )

    health = _as_mapping(metrics_map.get("health"))
    health_comparison = _as_mapping(health.get("summary"))
    # The refusal is consulted, never re-decided. ``compute_health`` owns the
    # four population states and already withheld the score; this only asks
    # the document's one reader whether a score exists for that state.
    # Coercing the withheld fields back through _as_int/str would restore the
    # 0/"F" verdict this document exists to stop repeating — and ``str(None)``
    # would write the grade as "None".
    #
    # ``bool(health)`` stays in front, and is a different question: a
    # clones-only run brings no health block at all and keeps its historical
    # empty shape. "Health was not computed" is a third fact, distinct from
    # both "computed over a population of nothing" and "computed over a
    # population nobody read", and only the last two are refusals.
    health_population = str(health.get("population", ""))
    health_unmeasured = bool(health) and health_verdict_withheld(health)
    health_dimensions: dict[str, int] | None = (
        None
        if health_unmeasured
        else {
            str(key): _as_int(value)
            for key, value in sorted(_as_mapping(health.get("dimensions")).items())
        }
    )
    overloaded_modules = _as_mapping(metrics_map.get(_OVERLOADED_MODULES_FAMILY))
    overloaded_modules_detection = _as_mapping(overloaded_modules.get("detection"))
    overloaded_module_items = sorted(
        (
            {
                "module": str(item_map.get("module", "")).strip(),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "source_kind": _normalized_source_kind(item_map.get("source_kind")),
                "loc": _as_int(item_map.get("loc")),
                "functions": _as_int(item_map.get("functions")),
                "methods": _as_int(item_map.get("methods")),
                "classes": _as_int(item_map.get("classes")),
                "callable_count": _as_int(item_map.get("callable_count")),
                "complexity_total": _as_int(item_map.get("complexity_total")),
                "complexity_max": _as_int(item_map.get("complexity_max")),
                "fan_in": _as_int(item_map.get("fan_in")),
                "fan_out": _as_int(item_map.get("fan_out")),
                "total_deps": _as_int(item_map.get("total_deps")),
                "import_edges": _as_int(item_map.get("import_edges")),
                "reimport_edges": _as_int(item_map.get("reimport_edges")),
                "reimport_ratio": round(
                    _as_float(item_map.get("reimport_ratio")),
                    4,
                ),
                "instability": round(_as_float(item_map.get("instability")), 4),
                "hub_balance": round(_as_float(item_map.get("hub_balance")), 4),
                "size_score": round(_as_float(item_map.get("size_score")), 4),
                "dependency_score": round(
                    _as_float(item_map.get("dependency_score")),
                    4,
                ),
                "shape_score": round(_as_float(item_map.get("shape_score")), 4),
                "score": round(_as_float(item_map.get("score")), 4),
                "candidate_status": str(
                    item_map.get("candidate_status", "non_candidate")
                ),
                "candidate_reasons": [
                    str(reason)
                    for reason in _as_sequence(item_map.get("candidate_reasons"))
                    if str(reason).strip()
                ],
            }
            for item in _as_sequence(overloaded_modules.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            {"candidate": 0, "ranked_only": 1, "non_candidate": 2}.get(
                str(item["candidate_status"]),
                3,
            ),
            -_as_float(item["score"]),
            -_as_float(item["size_score"]),
            -_as_float(item["dependency_score"]),
            item["relative_path"],
            item["module"],
        ),
    )

    complexity_summary = _as_mapping(complexity.get("summary"))
    coupling_summary = _as_mapping(coupling.get("summary"))
    cohesion_summary = _as_mapping(cohesion.get("summary"))
    dead_code_summary = _as_mapping(dead_code.get("summary"))
    overloaded_modules_summary = _as_mapping(overloaded_modules.get("summary"))
    coverage_adoption = _as_mapping(metrics_map.get(_COVERAGE_ADOPTION_FAMILY))
    coverage_adoption_summary = _as_mapping(coverage_adoption.get("summary"))
    coverage_adoption_items = sorted(
        (
            {
                "module": str(item_map.get("module", "")).strip(),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "callable_count": _as_int(item_map.get("callable_count")),
                "params_total": _as_int(item_map.get("params_total")),
                "params_annotated": _as_int(item_map.get("params_annotated")),
                "param_permille": _as_int(item_map.get("param_permille")),
                "returns_total": _as_int(item_map.get("returns_total")),
                "returns_annotated": _as_int(item_map.get("returns_annotated")),
                "return_permille": _as_int(item_map.get("return_permille")),
                "any_annotation_count": _as_int(item_map.get("any_annotation_count")),
                "public_symbol_total": _as_int(item_map.get("public_symbol_total")),
                "public_symbol_documented": _as_int(
                    item_map.get("public_symbol_documented")
                ),
                "docstring_permille": _as_int(item_map.get("docstring_permille")),
            }
            for item in _as_sequence(coverage_adoption.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["module"],
        ),
    )
    api_surface = _as_mapping(metrics_map.get(_API_SURFACE_FAMILY))
    api_surface_summary = _as_mapping(api_surface.get("summary"))
    api_surface_items = sorted(
        (
            {
                "record_kind": str(item_map.get("record_kind", "symbol")),
                "module": str(item_map.get("module", "")).strip(),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "qualname": str(item_map.get("qualname", "")),
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "symbol_kind": str(item_map.get("symbol_kind", "")),
                "exported_via": _optional_str(item_map.get("exported_via")),
                "params_total": _as_int(item_map.get("params_total")),
                "params": [
                    {
                        "name": str(param_map.get("name", "")),
                        "kind": str(param_map.get("kind", "")),
                        "has_default": bool(param_map.get("has_default")),
                        "annotated": bool(param_map.get("annotated")),
                    }
                    for param in _as_sequence(item_map.get("params"))
                    for param_map in (_as_mapping(param),)
                ],
                "returns_annotated": bool(item_map.get("returns_annotated")),
                "change_kind": _optional_str(item_map.get("change_kind")),
                "detail": _optional_str(item_map.get("detail")),
            }
            for item in _as_sequence(api_surface.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["record_kind"],
        ),
    )
    coverage_join = _as_mapping(metrics_map.get(_COVERAGE_JOIN_FAMILY))
    coverage_join_summary = _as_mapping(coverage_join.get("summary"))
    coverage_join_items = sorted(
        (
            {
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "qualname": str(item_map.get("qualname", "")).strip(),
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "cyclomatic_complexity": _as_int(
                    item_map.get("cyclomatic_complexity"),
                    1,
                ),
                "risk": str(item_map.get("risk", RISK_LOW)).strip() or RISK_LOW,
                "executable_lines": _as_int(item_map.get("executable_lines")),
                "covered_lines": _as_int(item_map.get("covered_lines")),
                "coverage_permille": _as_int(item_map.get("coverage_permille")),
                "coverage_status": str(item_map.get("coverage_status", "")).strip(),
                "coverage_hotspot": bool(item_map.get("coverage_hotspot")),
                "scope_gap_hotspot": bool(item_map.get("scope_gap_hotspot")),
            }
            for item in _as_sequence(coverage_join.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            0 if bool(item["coverage_hotspot"]) else 1,
            0 if bool(item["scope_gap_hotspot"]) else 1,
            {"high": 0, "medium": 1, "low": 2}.get(str(item["risk"]), 3),
            _as_int(item["coverage_permille"]),
            -_as_int(item["cyclomatic_complexity"]),
            item["relative_path"],
            _as_int(item["start_line"]),
            item["qualname"],
        ),
    )
    security_surfaces = _as_mapping(metrics_map.get(_SECURITY_SURFACES_FAMILY))
    security_surfaces_summary = _as_mapping(security_surfaces.get("summary"))
    raw_category_counts = _as_mapping(security_surfaces_summary.get("categories"))
    raw_source_kind_counts = _as_mapping(
        security_surfaces_summary.get("by_source_kind")
    )
    security_surface_items = sorted(
        (
            {
                "category": str(item_map.get("category", "")).strip(),
                "capability": str(item_map.get("capability", "")).strip(),
                "module": str(item_map.get("module", "")).strip(),
                "qualname": str(item_map.get("qualname", "")).strip(),
                "relative_path": _contract_path(
                    item_map.get("filepath", ""),
                    scan_root=scan_root,
                )[0]
                or "",
                "source_kind": str(item_map.get("source_kind", SOURCE_KIND_OTHER)),
                "start_line": _as_int(item_map.get("start_line")),
                "end_line": _as_int(item_map.get("end_line")),
                "location_scope": str(item_map.get("location_scope", "")).strip(),
                "classification_mode": str(
                    item_map.get("classification_mode", "")
                ).strip(),
                "evidence_kind": str(item_map.get("evidence_kind", "")).strip(),
                "evidence_symbol": str(item_map.get("evidence_symbol", "")).strip(),
            }
            for item in _as_sequence(security_surfaces.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["category"],
            item["capability"],
            item["evidence_symbol"],
        ),
    )
    semantic_authority = _as_mapping(metrics_map.get(_SEMANTIC_AUTHORITY_FAMILY))
    semantic_authority_summary = _as_mapping(semantic_authority.get("summary"))
    semantic_authority_items = sorted(
        (
            {
                "item_kind": str(item_map.get("item_kind", "")).strip(),
                "sink_identity": str(item_map.get("sink_identity", "")).strip(),
                "violation_id": str(item_map.get("violation_id", "")).strip(),
                "contract_id": str(item_map.get("contract_id", "")).strip(),
                "kind": str(item_map.get("kind", "")).strip(),
                "canonical_owner": str(item_map.get("canonical_owner", "")).strip(),
                "authority_status": str(item_map.get("authority_status", "")).strip(),
                "producer_root_ids": sorted(
                    str(value)
                    for value in _as_sequence(item_map.get("producer_root_ids"))
                ),
                "effect_signature": str(item_map.get("effect_signature", "")).strip(),
                "resolution_state": str(item_map.get("resolution_state", "")).strip(),
                # An abstaining row carries why it abstained: a status without
                # its reason is the difference between "clean" and "cannot see".
                "unresolved_reasons": [
                    str(value).strip()
                    for value in _as_sequence(item_map.get("unresolved_reasons"))
                    if str(value).strip()
                ],
                "candidate_id": str(item_map.get("candidate_id", "")).strip(),
                "level": str(item_map.get("level", "")).strip(),
                "score": _as_int(item_map.get("score")),
                "producers": sorted(
                    str(value) for value in _as_sequence(item_map.get("producers"))
                ),
                "shared_fact": str(item_map.get("shared_fact", "")).strip(),
                # The kind the ranking used, recorded so the order it produces
                # can be read back instead of inferred.
                "source_kind": _producer_source_kind(
                    [str(value) for value in _as_sequence(item_map.get("producers"))]
                ),
                "independence": bool(item_map.get("independence")),
                "semantic_divergence": bool(item_map.get("semantic_divergence")),
                "suppressed": bool(item_map.get("suppressed")),
                "locations": [
                    {
                        "relative_path": _contract_path(
                            location_map.get("relative_path", ""),
                            scan_root=scan_root,
                        )[0]
                        or "",
                        "start_line": _as_int(location_map.get("start_line")),
                        "end_line": _as_int(location_map.get("end_line")),
                        "qualname": str(location_map.get("qualname", "")).strip(),
                    }
                    for location in _as_sequence(item_map.get("locations"))
                    for location_map in (_as_mapping(location),)
                ],
                "sink_statuses": [
                    str(value) for value in _as_sequence(item_map.get("sink_statuses"))
                ],
                "algorithm_revision": str(
                    item_map.get("algorithm_revision", "")
                ).strip(),
            }
            for item in _as_sequence(semantic_authority.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["item_kind"],
            item["contract_id"],
            item["sink_identity"],
            item["kind"],
            # Discovery candidates rank by evidence strength first, then by the
            # code they touch (production ahead of tests and fixtures, as an
            # ordering term and never a filter), then by how many producers the
            # consolidation would settle. The identity tail keeps it total.
            -_as_int(item["score"]),
            SOURCE_KIND_ORDER.get(
                str(item["source_kind"]),
                len(SOURCE_KIND_ORDER),
            ),
            -len(_as_sequence(item["producers"])),
            item["candidate_id"],
        ),
    )
    semantic_authority_registry = sorted(
        (
            {
                "contract_id": str(item_map.get("contract_id", "")).strip(),
                "canonical_owner": str(item_map.get("canonical_owner", "")).strip(),
                "allowed_adapters": sorted(
                    str(value)
                    for value in _as_sequence(item_map.get("allowed_adapters"))
                ),
                "forbidden_raw_inputs": sorted(
                    str(value)
                    for value in _as_sequence(item_map.get("forbidden_raw_inputs"))
                ),
                "required_provenance": sorted(
                    str(value)
                    for value in _as_sequence(item_map.get("required_provenance"))
                ),
            }
            for item in _as_sequence(semantic_authority.get("registry"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: str(item["contract_id"]),
    )
    semantic_authority_contracts: list[dict[str, object]] = sorted(
        [
            {
                "function": str(item_map.get("function", "")).strip(),
                "wire": str(item_map.get("wire", "")),
                "effect_signature": str(item_map.get("effect_signature", "")).strip(),
                "producer_root_ids": sorted(
                    str(value)
                    for value in _as_sequence(item_map.get("producer_root_ids"))
                ),
            }
            for item in _as_sequence(semantic_authority.get("contract_ir"))
            for item_map in (_as_mapping(item),)
        ],
        key=lambda item: str(item["function"]),
    )
    dead_high_confidence = sum(
        1
        for item in dead_items
        if str(_as_mapping(item).get("confidence", "")).strip().lower()
        == CONFIDENCE_HIGH
    )

    family_sections: dict[str, object] = {
        CATEGORY_COMPLEXITY: {
            "summary": {
                "total": len(complexity_items),
                "average": round(_as_float(complexity_summary.get("average")), 2),
                "max": _as_int(complexity_summary.get("max")),
                "high_risk": _as_int(complexity_summary.get("high_risk")),
                "baseline_diff_available": bool(
                    complexity_summary.get("baseline_diff_available")
                ),
                "new_high_risk": _as_int(complexity_summary.get("new_high_risk")),
            },
            "items": complexity_items,
            "items_truncated": False,
        },
        CATEGORY_COUPLING: {
            "summary": {
                "total": len(coupling_items),
                "average": round(_as_float(coupling_summary.get("average")), 2),
                "max": _as_int(coupling_summary.get("max")),
                "high_risk": _as_int(coupling_summary.get("high_risk")),
                "baseline_diff_available": bool(
                    coupling_summary.get("baseline_diff_available")
                ),
                "new_high_risk": _as_int(coupling_summary.get("new_high_risk")),
            },
            "items": coupling_items,
            "items_truncated": False,
        },
        CATEGORY_COHESION: {
            "summary": {
                "total": len(cohesion_items),
                "average": round(_as_float(cohesion_summary.get("average")), 2),
                "max": _as_int(cohesion_summary.get("max")),
                "low_cohesion": _as_int(cohesion_summary.get("low_cohesion")),
            },
            "items": cohesion_items,
            "items_truncated": False,
        },
        "dependencies": {
            "summary": {
                "modules": _as_int(dependencies.get("modules")),
                "edges": _as_int(dependencies.get("edges")),
                "cycles": len(dependency_cycles),
                # The kind split rides beside the total so every consumer of
                # this document — the gate evaluator above all — can apply
                # cycle policy without re-deriving the classification.
                "import_cycles": _cycle_kind_count(
                    dependency_cycle_details,
                    kind="import_cycle",
                    cycles_total=len(dependency_cycles),
                ),
                "deferred_cycles": _cycle_kind_count(
                    dependency_cycle_details,
                    kind="deferred_cycle",
                    cycles_total=len(dependency_cycles),
                ),
                "max_depth": _as_int(dependencies.get("max_depth")),
                "avg_depth": round(_as_float(dependencies.get("avg_depth")), 2),
                "p95_depth": _as_int(dependencies.get("p95_depth")),
                "baseline_diff_available": bool(
                    dependencies_comparison.get("baseline_diff_available")
                ),
                "new_cycles": _as_int(dependencies_comparison.get("new_cycles")),
                "new_import_cycles": _as_int(
                    dependencies_comparison.get("new_import_cycles")
                ),
                "new_deferred_cycles": _as_int(
                    dependencies_comparison.get("new_deferred_cycles")
                ),
            },
            "items": dependency_edges,
            "cycles": dependency_cycles,
            "cycle_details": dependency_cycle_details,
            "longest_chains": longest_chains,
            "dynamic_boundaries": dynamic_boundaries,
            "items_truncated": False,
        },
        FAMILY_DEAD_CODE: {
            "summary": {
                "total": len(dead_items),
                "high_confidence": dead_high_confidence
                or _as_int(
                    dead_code_summary.get(
                        "high_confidence", dead_code_summary.get("critical")
                    )
                ),
                "suppressed": len(dead_suppressed_items)
                or _as_int(dead_code_summary.get("suppressed")),
                "baseline_diff_available": bool(
                    dead_code_summary.get("baseline_diff_available")
                ),
                "new_items": _as_int(dead_code_summary.get("new_items")),
                # Carried verbatim: the report document is the evidence the
                # MCP gate path reads, so dropping the abstention count here
                # would make --fail-on-unresolved-dead-code inert on that
                # surface exactly as it was on the CLI one.
                "unresolved_external_override": _as_int(
                    dead_code_summary.get("unresolved_external_override")
                ),
                # Carried forward, never recomputed here: the metrics payload
                # owns this count, and every surface reading this document —
                # text, markdown, HTML and the gate — takes it from here.
                "unreachable_statements": _as_int(
                    dead_code_summary.get("unreachable_statements")
                ),
                "live_roots": _as_int(dead_code_summary.get("live_roots")),
            },
            "items": dead_items,
            "suppressed_items": dead_suppressed_items,
            "unresolved_overrides": dead_unresolved_overrides,
            # Projected, not merely computed: the findings builder reads this
            # document rather than the raw metrics payload, so a list left out
            # here is dropped before any finding is built and the detector goes
            # silent while its own unit tests still pass (39Y Y9).
            "unreachable_statements": dead_unreachable_statements,
            "live_root_reasons": dead_live_root_reasons,
            "items_truncated": False,
        },
        "health": {
            "summary": {
                "score": None if health_unmeasured else _as_int(health.get("score")),
                "grade": (None if health_unmeasured else str(health.get("grade", ""))),
                "dimensions": health_dimensions,
                # Always emitted, so a consumer never has to read the absence
                # of a key as an answer.
                "population": health_population,
                "baseline_diff_available": bool(
                    health_comparison.get("baseline_diff_available")
                ),
                "delta": _as_int(health_comparison.get("delta")),
            },
            "items": [],
            "items_truncated": False,
        },
        _COVERAGE_ADOPTION_FAMILY: {
            "summary": {
                "modules": len(coverage_adoption_items),
                "params_total": _as_int(coverage_adoption_summary.get("params_total")),
                "params_annotated": _as_int(
                    coverage_adoption_summary.get("params_annotated")
                ),
                "param_permille": _as_int(
                    coverage_adoption_summary.get("param_permille")
                ),
                "baseline_diff_available": bool(
                    coverage_adoption_summary.get("baseline_diff_available")
                ),
                "param_delta": _as_int(coverage_adoption_summary.get("param_delta")),
                "returns_total": _as_int(
                    coverage_adoption_summary.get("returns_total")
                ),
                "returns_annotated": _as_int(
                    coverage_adoption_summary.get("returns_annotated")
                ),
                "return_permille": _as_int(
                    coverage_adoption_summary.get("return_permille")
                ),
                "return_delta": _as_int(coverage_adoption_summary.get("return_delta")),
                "public_symbol_total": _as_int(
                    coverage_adoption_summary.get("public_symbol_total")
                ),
                "public_symbol_documented": _as_int(
                    coverage_adoption_summary.get("public_symbol_documented")
                ),
                "docstring_permille": _as_int(
                    coverage_adoption_summary.get("docstring_permille")
                ),
                "docstring_delta": _as_int(
                    coverage_adoption_summary.get("docstring_delta")
                ),
                "typing_any_count": _as_int(
                    coverage_adoption_summary.get("typing_any_count")
                ),
            },
            "items": coverage_adoption_items,
            "items_truncated": False,
        },
        _API_SURFACE_FAMILY: {
            "summary": {
                "enabled": bool(api_surface_summary.get("enabled")),
                "baseline_diff_available": bool(
                    api_surface_summary.get("baseline_diff_available")
                ),
                "modules": _as_int(api_surface_summary.get("modules")),
                "public_symbols": _as_int(api_surface_summary.get("public_symbols")),
                "added": _as_int(api_surface_summary.get("added")),
                "breaking": _as_int(api_surface_summary.get("breaking")),
                "strict_types": bool(api_surface_summary.get("strict_types")),
            },
            "items": api_surface_items,
            "items_truncated": False,
        },
        _OVERLOADED_MODULES_FAMILY: {
            "summary": {
                "total": len(overloaded_module_items),
                "candidates": _as_int(overloaded_modules_summary.get("candidates")),
                "population_status": str(
                    overloaded_modules_summary.get("population_status", "limited")
                ),
                "top_score": round(
                    _as_float(overloaded_modules_summary.get("top_score")),
                    4,
                ),
                "average_score": round(
                    _as_float(overloaded_modules_summary.get("average_score")),
                    4,
                ),
                "candidate_score_cutoff": round(
                    _as_float(overloaded_modules_summary.get("candidate_score_cutoff")),
                    4,
                ),
            },
            "detection": {
                "version": str(overloaded_modules_detection.get("version", "1")),
                "scope": str(overloaded_modules_detection.get("scope", "report_only")),
                "strategy": str(
                    overloaded_modules_detection.get(
                        "strategy",
                        "project_relative_composite",
                    )
                ),
                "minimum_population": _as_int(
                    overloaded_modules_detection.get("minimum_population"),
                ),
                "size_signals": [
                    str(signal)
                    for signal in _as_sequence(
                        overloaded_modules_detection.get("size_signals")
                    )
                    if str(signal).strip()
                ],
                "dependency_signals": [
                    str(signal)
                    for signal in _as_sequence(
                        overloaded_modules_detection.get("dependency_signals")
                    )
                    if str(signal).strip()
                ],
                "shape_signals": [
                    str(signal)
                    for signal in _as_sequence(
                        overloaded_modules_detection.get("shape_signals")
                    )
                    if str(signal).strip()
                ],
            },
            "items": overloaded_module_items,
            "items_truncated": False,
        },
        _SECURITY_SURFACES_FAMILY: {
            "summary": {
                "items": _as_int(security_surfaces_summary.get("items")),
                "modules": _as_int(security_surfaces_summary.get("modules")),
                "exact_items": _as_int(security_surfaces_summary.get("exact_items")),
                "category_count": _as_int(
                    security_surfaces_summary.get("category_count")
                ),
                "categories": {
                    str(key): _as_int(value)
                    for key, value in sorted(raw_category_counts.items())
                    if str(key).strip()
                },
                "by_source_kind": {
                    SOURCE_KIND_PRODUCTION: _as_int(
                        raw_source_kind_counts.get(SOURCE_KIND_PRODUCTION)
                    ),
                    SOURCE_KIND_TESTS: _as_int(
                        raw_source_kind_counts.get(SOURCE_KIND_TESTS)
                    ),
                    SOURCE_KIND_FIXTURES: _as_int(
                        raw_source_kind_counts.get(SOURCE_KIND_FIXTURES)
                    ),
                    SOURCE_KIND_OTHER: _as_int(
                        raw_source_kind_counts.get(SOURCE_KIND_OTHER)
                    ),
                },
                "production": _as_int(security_surfaces_summary.get("production")),
                "tests": _as_int(security_surfaces_summary.get("tests")),
                "fixtures": _as_int(security_surfaces_summary.get("fixtures")),
                "other": _as_int(security_surfaces_summary.get("other")),
                "report_only": bool(security_surfaces_summary.get("report_only")),
            },
            "items": security_surface_items,
            "items_truncated": False,
        },
    }
    if semantic_authority:
        raw_status_counts = _as_mapping(
            semantic_authority_summary.get("sinks_by_status")
        )
        family_sections[_SEMANTIC_AUTHORITY_FAMILY] = {
            "summary": {
                "enabled": bool(semantic_authority_summary.get("enabled")),
                "report_only": bool(semantic_authority_summary.get("report_only")),
                "enforcement_enabled": bool(
                    semantic_authority_summary.get("enforcement_enabled")
                ),
                "algorithm_revision": str(
                    semantic_authority_summary.get("algorithm_revision", "")
                ),
                "registry_version": str(
                    semantic_authority_summary.get("registry_version", "")
                ),
                "registry_contracts": _as_int(
                    semantic_authority_summary.get("registry_contracts")
                ),
                "contracts": _as_int(semantic_authority_summary.get("contracts")),
                "sinks": _as_int(semantic_authority_summary.get("sinks")),
                "candidates": _as_int(semantic_authority_summary.get("candidates")),
                "governed_sinks": _as_int(
                    semantic_authority_summary.get("governed_sinks")
                ),
                "violations": _as_int(semantic_authority_summary.get("violations")),
                "active_violations": _as_int(
                    semantic_authority_summary.get("active_violations")
                ),
                "suppressed_violations": _as_int(
                    semantic_authority_summary.get("suppressed_violations")
                ),
                "scc_count": _as_int(semantic_authority_summary.get("scc_count")),
                "fixpoint_iterations": _as_int(
                    semantic_authority_summary.get("fixpoint_iterations")
                ),
                "sinks_by_status": {
                    status: _as_int(raw_status_counts.get(status))
                    for status in (
                        "authoritative",
                        "adapter",
                        "shadow",
                        "mixed",
                        "unavailable",
                    )
                },
            },
            "items": semantic_authority_items,
            "registry": semantic_authority_registry,
            "contract_ir": semantic_authority_contracts,
            "items_truncated": False,
        }
    if coverage_join_summary or coverage_join_items or coverage_join:
        family_sections[_COVERAGE_JOIN_FAMILY] = {
            "summary": {
                "status": str(coverage_join_summary.get("status", "")),
                "source": _contract_path(
                    coverage_join_summary.get("source", ""),
                    scan_root=scan_root,
                )[0],
                "files": _as_int(coverage_join_summary.get("files")),
                "units": _as_int(coverage_join_summary.get("units")),
                "measured_units": _as_int(coverage_join_summary.get("measured_units")),
                "overall_executable_lines": _as_int(
                    coverage_join_summary.get("overall_executable_lines")
                ),
                "overall_covered_lines": _as_int(
                    coverage_join_summary.get("overall_covered_lines")
                ),
                "overall_permille": _as_int(
                    coverage_join_summary.get("overall_permille")
                ),
                "missing_from_report_units": _as_int(
                    coverage_join_summary.get("missing_from_report_units")
                ),
                "coverage_hotspots": _as_int(
                    coverage_join_summary.get("coverage_hotspots")
                ),
                "scope_gap_hotspots": _as_int(
                    coverage_join_summary.get("scope_gap_hotspots")
                ),
                "hotspot_threshold_percent": _as_int(
                    coverage_join_summary.get("hotspot_threshold_percent")
                ),
                "invalid_reason": _optional_str(
                    coverage_join_summary.get("invalid_reason")
                ),
            },
            "items": coverage_join_items,
            "items_truncated": False,
        }
    normalized: dict[str, object] = {}
    for family in METRIC_FAMILIES.values():
        section = family.report_section
        if section in family_sections:
            normalized[section] = family_sections[section]
    return normalized


def _build_metrics_payload(
    metrics: Mapping[str, object] | None,
    *,
    scan_root: str,
) -> dict[str, object]:
    families = _normalize_metrics_families(metrics, scan_root=scan_root)
    return {
        "summary": {
            family_name: _as_mapping(_as_mapping(family_payload).get("summary"))
            for family_name, family_payload in families.items()
        },
        "families": families,
    }
