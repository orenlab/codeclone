# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from .. import _coerce
from ..contracts import REPORT_SCHEMA_VERSION
from ..domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    CLONE_NOVELTY_KNOWN,
    CLONE_NOVELTY_NEW,
    FAMILY_CLONE,
    FAMILY_CLONES,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_STRUCTURAL,
)
from ..domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    EFFORT_EASY,
    EFFORT_HARD,
    EFFORT_MODERATE,
    EFFORT_WEIGHT,
    RISK_LOW,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_ORDER,
    SEVERITY_RANK,
    SEVERITY_WARNING,
)
from ..domain.source_scope import (
    IMPACT_SCOPE_MIXED,
    IMPACT_SCOPE_NON_RUNTIME,
    IMPACT_SCOPE_RUNTIME,
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_MIXED,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from ..structural_findings import normalize_structural_findings
from .derived import (
    combine_source_kinds,
    group_spread,
    relative_report_path,
    report_location_from_group_item,
    report_location_from_structural_occurrence,
)
from .suggestions import classify_clone_type

if TYPE_CHECKING:
    from ..models import (
        GroupItemLike,
        GroupMapLike,
        SourceKind,
        StructuralFindingGroup,
        Suggestion,
    )

__all__ = [
    "build_report_document",
    "clone_group_id",
    "dead_code_group_id",
    "design_group_id",
    "structural_group_id",
]

_as_int = _coerce.as_int
_as_float = _coerce.as_float
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence

_SOURCE_BREAKDOWN_KEYS_TYPED: tuple[SourceKind, ...] = (
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_OTHER,
)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def _is_absolute_path(value: str) -> bool:
    normalized = _normalize_path(value)
    if not normalized:
        return False
    if normalized.startswith("/"):
        return True
    return len(normalized) > 2 and normalized[1] == ":" and normalized[2] == "/"


def _contract_path(
    value: object,
    *,
    scan_root: str,
) -> tuple[str | None, str | None, str | None]:
    path_text = _optional_str(value)
    if path_text is None:
        return None, None, None
    normalized_path = _normalize_path(path_text)
    relative_path = relative_report_path(normalized_path, scan_root=scan_root)
    if relative_path and relative_path != normalized_path:
        return relative_path, "in_root", normalized_path
    if _is_absolute_path(normalized_path):
        return normalized_path.rsplit("/", maxsplit=1)[-1], "external", normalized_path
    return normalized_path, "relative", None


def _contract_report_location_path(location_path: str, *, scan_root: str) -> str:
    contract_path, _scope, _absolute = _contract_path(
        location_path,
        scan_root=scan_root,
    )
    return contract_path or ""


def _priority(
    severity: str,
    effort: str,
) -> float:
    severity_rank = SEVERITY_RANK.get(severity, 1)
    effort_rank = EFFORT_WEIGHT.get(effort, 1)
    return float(severity_rank) / float(effort_rank)


def clone_group_id(kind: str, group_key: str) -> str:
    return f"clone:{kind}:{group_key}"


def structural_group_id(finding_kind: str, finding_key: str) -> str:
    return f"structural:{finding_kind}:{finding_key}"


def dead_code_group_id(subject_key: str) -> str:
    return f"dead_code:{subject_key}"


def design_group_id(category: str, subject_key: str) -> str:
    return f"design:{category}:{subject_key}"


def _clone_novelty(
    *,
    group_key: str,
    baseline_trusted: bool,
    new_keys: Collection[str] | None,
) -> str:
    if not baseline_trusted:
        return CLONE_NOVELTY_NEW
    if new_keys is None:
        return CLONE_NOVELTY_NEW
    return CLONE_NOVELTY_NEW if group_key in new_keys else CLONE_NOVELTY_KNOWN


def _item_sort_key(item: Mapping[str, object]) -> tuple[str, int, int, str]:
    return (
        str(item.get("relative_path", "")),
        _as_int(item.get("start_line")),
        _as_int(item.get("end_line")),
        str(item.get("qualname", "")),
    )


def _parse_bool_text(value: object) -> bool:
    text = str(value).strip().lower()
    return text in {"1", "true", "yes"}


def _parse_ratio_percent(value: object) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100.0
        except ValueError:
            return None
    try:
        numeric = float(text)
    except ValueError:
        return None
    return numeric if numeric <= 1.0 else numeric / 100.0


def _normalize_block_machine_facts(
    *,
    group_key: str,
    group_arity: int,
    block_facts: Mapping[str, str],
) -> tuple[dict[str, object], dict[str, str]]:
    facts: dict[str, object] = {
        "group_key": group_key,
        "group_arity": group_arity,
    }
    display_facts: dict[str, str] = {}
    for key in sorted(block_facts):
        value = str(block_facts[key])
        match key:
            case "group_arity":
                facts[key] = _as_int(value)
            case "block_size" | "consecutive_asserts" | "instance_peer_count":
                facts[key] = _as_int(value)
            case "merged_regions":
                facts[key] = _parse_bool_text(value)
            case "assert_ratio":
                ratio = _parse_ratio_percent(value)
                if ratio is not None:
                    facts[key] = ratio
                display_facts[key] = value
            case (
                "match_rule" | "pattern" | "signature_kind" | "hint" | "hint_confidence"
            ):
                facts[key] = value
            case _:
                display_facts[key] = value
    return facts, display_facts


def _source_scope_from_filepaths(
    filepaths: Iterable[str],
    *,
    scan_root: str,
) -> dict[str, object]:
    counts: Counter[SourceKind] = Counter()
    for filepath in filepaths:
        location = report_location_from_group_item(
            {"filepath": filepath, "start_line": 0, "end_line": 0, "qualname": ""},
            scan_root=scan_root,
        )
        counts[location.source_kind] += 1
    breakdown = {kind: counts[kind] for kind in _SOURCE_BREAKDOWN_KEYS_TYPED}
    present = tuple(
        kind for kind in _SOURCE_BREAKDOWN_KEYS_TYPED if breakdown[kind] > 0
    )
    dominant_kind = (
        present[0]
        if len(present) == 1
        else combine_source_kinds(present)
        if present
        else SOURCE_KIND_OTHER
    )
    production_count = breakdown[SOURCE_KIND_PRODUCTION]
    non_runtime_count = (
        breakdown[SOURCE_KIND_TESTS]
        + breakdown[SOURCE_KIND_FIXTURES]
        + breakdown[SOURCE_KIND_OTHER]
    )
    match (production_count > 0, non_runtime_count == 0, production_count == 0):
        case (True, True, _):
            impact_scope = IMPACT_SCOPE_RUNTIME
        case (_, _, True):
            impact_scope = IMPACT_SCOPE_NON_RUNTIME
        case _:
            impact_scope = IMPACT_SCOPE_MIXED
    return {
        "dominant_kind": dominant_kind,
        "breakdown": breakdown,
        "impact_scope": impact_scope,
    }


def _source_scope_from_locations(
    locations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    counts: Counter[SourceKind] = Counter()
    for location in locations:
        source_kind_text = (
            str(location.get("source_kind", SOURCE_KIND_OTHER)).strip().lower()
            or SOURCE_KIND_OTHER
        )
        if source_kind_text == SOURCE_KIND_PRODUCTION:
            source_kind: SourceKind = SOURCE_KIND_PRODUCTION
        elif source_kind_text == SOURCE_KIND_TESTS:
            source_kind = SOURCE_KIND_TESTS
        elif source_kind_text == SOURCE_KIND_FIXTURES:
            source_kind = SOURCE_KIND_FIXTURES
        else:
            source_kind = SOURCE_KIND_OTHER
        counts[source_kind] += 1
    breakdown = {kind: counts[kind] for kind in _SOURCE_BREAKDOWN_KEYS_TYPED}
    present = tuple(
        kind for kind in _SOURCE_BREAKDOWN_KEYS_TYPED if breakdown[kind] > 0
    )
    dominant_kind = (
        present[0]
        if len(present) == 1
        else combine_source_kinds(present)
        if present
        else SOURCE_KIND_OTHER
    )
    production_count = breakdown[SOURCE_KIND_PRODUCTION]
    non_runtime_count = (
        breakdown[SOURCE_KIND_TESTS]
        + breakdown[SOURCE_KIND_FIXTURES]
        + breakdown[SOURCE_KIND_OTHER]
    )
    match (production_count > 0, non_runtime_count == 0, production_count == 0):
        case (True, True, _):
            impact_scope = IMPACT_SCOPE_RUNTIME
        case (_, _, True):
            impact_scope = IMPACT_SCOPE_NON_RUNTIME
        case _:
            impact_scope = IMPACT_SCOPE_MIXED
    return {
        "dominant_kind": dominant_kind,
        "breakdown": breakdown,
        "impact_scope": impact_scope,
    }


def _collect_paths_from_metrics(metrics: Mapping[str, object]) -> set[str]:
    paths: set[str] = set()
    complexity = _as_mapping(metrics.get(CATEGORY_COMPLEXITY))
    for item in _as_sequence(complexity.get("functions")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    for family_name in (CATEGORY_COUPLING, CATEGORY_COHESION):
        family = _as_mapping(metrics.get(family_name))
        for item in _as_sequence(family.get("classes")):
            item_map = _as_mapping(item)
            filepath = _optional_str(item_map.get("filepath"))
            if filepath is not None:
                paths.add(filepath)
    dead_code = _as_mapping(metrics.get(FAMILY_DEAD_CODE))
    for item in _as_sequence(dead_code.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    for item in _as_sequence(dead_code.get("suppressed_items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    return paths


def _collect_report_file_list(
    *,
    inventory: Mapping[str, object] | None,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    metrics: Mapping[str, object] | None,
    structural_findings: Sequence[StructuralFindingGroup] | None,
) -> list[str]:
    files: set[str] = set()
    inventory_map = _as_mapping(inventory)
    for filepath in _as_sequence(inventory_map.get("file_list")):
        file_text = _optional_str(filepath)
        if file_text is not None:
            files.add(file_text)
    for groups in (func_groups, block_groups, segment_groups):
        for items in groups.values():
            for item in items:
                filepath = _optional_str(item.get("filepath"))
                if filepath is not None:
                    files.add(filepath)
    if metrics is not None:
        files.update(_collect_paths_from_metrics(metrics))
    if structural_findings:
        for group in normalize_structural_findings(structural_findings):
            for occurrence in group.items:
                filepath = _optional_str(occurrence.file_path)
                if filepath is not None:
                    files.add(filepath)
    return sorted(files)


def _count_file_lines(filepaths: Sequence[str]) -> int:
    total = 0
    for filepath in filepaths:
        total += _count_file_lines_for_path(filepath)
    return total


def _count_file_lines_for_path(filepath: str) -> int:
    try:
        with open(filepath, encoding="utf-8", errors="surrogateescape") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _normalize_nested_string_rows(value: object) -> list[list[str]]:
    rows: list[tuple[str, ...]] = []
    for row in _as_sequence(value):
        modules = tuple(
            str(module) for module in _as_sequence(row) if str(module).strip()
        )
        if modules:
            rows.append(modules)
    rows.sort(key=lambda row: (len(row), row))
    return [list(row) for row in rows]


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
                "nesting_depth": _as_int(item_map.get("nesting_depth")),
                "risk": str(item_map.get("risk", RISK_LOW)),
            }
            for item in _as_sequence(complexity.get("functions"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
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
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
        ),
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
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
        ),
    )

    dependencies = _as_mapping(metrics_map.get("dependencies"))
    dependency_edges = sorted(
        (
            {
                "source": str(item_map.get("source", "")),
                "target": str(item_map.get("target", "")),
                "import_type": str(item_map.get("import_type", "")),
                "line": _as_int(item_map.get("line")),
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
    dependency_cycles = _normalize_nested_string_rows(dependencies.get("cycles"))
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
            {"rule": rule, "source": source or "inline_noqa"}
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
            }
            for item in _as_sequence(dead_code.get("items"))
            for item_map in (_as_mapping(item),)
        ),
        key=lambda item: (
            item["relative_path"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["kind"],
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

    health = _as_mapping(metrics_map.get("health"))
    health_dimensions = {
        str(key): _as_int(value)
        for key, value in sorted(_as_mapping(health.get("dimensions")).items())
    }

    complexity_summary = _as_mapping(complexity.get("summary"))
    coupling_summary = _as_mapping(coupling.get("summary"))
    cohesion_summary = _as_mapping(cohesion.get("summary"))
    dead_code_summary = _as_mapping(dead_code.get("summary"))
    dead_high_confidence = sum(
        1
        for item in dead_items
        if str(_as_mapping(item).get("confidence", "")).strip().lower()
        == CONFIDENCE_HIGH
    )

    normalized: dict[str, object] = {
        CATEGORY_COMPLEXITY: {
            "summary": {
                "total": len(complexity_items),
                "average": round(_as_float(complexity_summary.get("average")), 2),
                "max": _as_int(complexity_summary.get("max")),
                "high_risk": _as_int(complexity_summary.get("high_risk")),
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
                "max_depth": _as_int(dependencies.get("max_depth")),
            },
            "items": dependency_edges,
            "cycles": dependency_cycles,
            "longest_chains": longest_chains,
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
            },
            "items": dead_items,
            "suppressed_items": dead_suppressed_items,
            "items_truncated": False,
        },
        "health": {
            "summary": {
                "score": _as_int(health.get("score")),
                "grade": str(health.get("grade", "")),
                "dimensions": health_dimensions,
            },
            "items": [],
            "items_truncated": False,
        },
    }
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


def _derive_inventory_code_counts(
    *,
    metrics_payload: Mapping[str, object],
    inventory_code: Mapping[str, object],
    file_list: Sequence[str],
    cached_files: int,
) -> dict[str, object]:
    complexity = _as_mapping(
        _as_mapping(metrics_payload.get("families")).get(CATEGORY_COMPLEXITY)
    )
    cohesion = _as_mapping(
        _as_mapping(metrics_payload.get("families")).get(CATEGORY_COHESION)
    )
    complexity_items = _as_sequence(complexity.get("items"))
    cohesion_items = _as_sequence(cohesion.get("items"))

    exact_entities = bool(complexity_items or cohesion_items)
    method_count = sum(
        _as_int(_as_mapping(item).get("method_count")) for item in cohesion_items
    )
    class_count = len(cohesion_items)
    function_total = max(len(complexity_items) - method_count, 0)

    if not exact_entities:
        function_total = _as_int(inventory_code.get("functions"))
        method_count = _as_int(inventory_code.get("methods"))
        class_count = _as_int(inventory_code.get("classes"))

    parsed_lines_raw = inventory_code.get("parsed_lines")
    if isinstance(parsed_lines_raw, int) and parsed_lines_raw >= 0:
        parsed_lines = parsed_lines_raw
    elif cached_files > 0 and file_list:
        parsed_lines = _count_file_lines(file_list)
    else:
        parsed_lines = _as_int(parsed_lines_raw)

    if exact_entities and ((cached_files > 0 and file_list) or parsed_lines > 0):
        scope = "analysis_root"
    elif cached_files > 0 and file_list:
        scope = "mixed"
    else:
        scope = "current_run"

    return {
        "scope": scope,
        "parsed_lines": parsed_lines,
        "functions": function_total,
        "methods": method_count,
        "classes": class_count,
    }


def _build_inventory_payload(
    *,
    inventory: Mapping[str, object] | None,
    file_list: Sequence[str],
    metrics_payload: Mapping[str, object],
    scan_root: str,
) -> dict[str, object]:
    inventory_map = _as_mapping(inventory)
    files_map = _as_mapping(inventory_map.get("files"))
    code_map = _as_mapping(inventory_map.get("code"))
    cached_files = _as_int(files_map.get("cached"))
    file_registry = [
        path
        for path in (
            _contract_path(filepath, scan_root=scan_root)[0] for filepath in file_list
        )
        if path is not None
    ]
    return {
        "files": {
            "total_found": _as_int(files_map.get("total_found"), len(file_list)),
            "analyzed": _as_int(files_map.get("analyzed")),
            "cached": cached_files,
            "skipped": _as_int(files_map.get("skipped")),
            "source_io_skipped": _as_int(files_map.get("source_io_skipped")),
        },
        "code": _derive_inventory_code_counts(
            metrics_payload=metrics_payload,
            inventory_code=code_map,
            file_list=file_list,
            cached_files=cached_files,
        ),
        "file_registry": {
            "encoding": "relative_path",
            "items": file_registry,
        },
    }


def _baseline_is_trusted(meta: Mapping[str, object]) -> bool:
    baseline = _as_mapping(meta.get("baseline"))
    return (
        baseline.get("loaded") is True
        and str(baseline.get("status", "")).strip().lower() == "ok"
    )


def _build_meta_payload(
    raw_meta: Mapping[str, object] | None,
    *,
    scan_root: str,
) -> dict[str, object]:
    meta = dict(raw_meta or {})
    metrics_computed = sorted(
        {
            str(item)
            for item in _as_sequence(meta.get("metrics_computed"))
            if str(item).strip()
        }
    )
    baseline_path, baseline_path_scope, baseline_abs = _contract_path(
        meta.get("baseline_path"),
        scan_root=scan_root,
    )
    cache_path, cache_path_scope, cache_abs = _contract_path(
        meta.get("cache_path"),
        scan_root=scan_root,
    )
    metrics_baseline_path, metrics_baseline_path_scope, metrics_baseline_abs = (
        _contract_path(
            meta.get("metrics_baseline_path"),
            scan_root=scan_root,
        )
    )
    return {
        "codeclone_version": str(meta.get("codeclone_version", "")),
        "project_name": str(meta.get("project_name", "")),
        "scan_root": ".",
        "python_version": str(meta.get("python_version", "")),
        "python_tag": str(meta.get("python_tag", "")),
        "analysis_mode": str(meta.get("analysis_mode", "full") or "full"),
        "report_mode": str(meta.get("report_mode", "full") or "full"),
        "computed_metric_families": metrics_computed,
        "baseline": {
            "path": baseline_path,
            "path_scope": baseline_path_scope,
            "loaded": bool(meta.get("baseline_loaded")),
            "status": _optional_str(meta.get("baseline_status")),
            "fingerprint_version": _optional_str(
                meta.get("baseline_fingerprint_version")
            ),
            "schema_version": _optional_str(meta.get("baseline_schema_version")),
            "python_tag": _optional_str(meta.get("baseline_python_tag")),
            "generator_name": _optional_str(meta.get("baseline_generator_name")),
            "generator_version": _optional_str(meta.get("baseline_generator_version")),
            "payload_sha256": _optional_str(meta.get("baseline_payload_sha256")),
            "payload_sha256_verified": bool(
                meta.get("baseline_payload_sha256_verified")
            ),
        },
        "cache": {
            "path": cache_path,
            "path_scope": cache_path_scope,
            "used": bool(meta.get("cache_used")),
            "status": _optional_str(meta.get("cache_status")),
            "schema_version": _optional_str(meta.get("cache_schema_version")),
        },
        "metrics_baseline": {
            "path": metrics_baseline_path,
            "path_scope": metrics_baseline_path_scope,
            "loaded": bool(meta.get("metrics_baseline_loaded")),
            "status": _optional_str(meta.get("metrics_baseline_status")),
            "schema_version": _optional_str(
                meta.get("metrics_baseline_schema_version")
            ),
            "payload_sha256": _optional_str(
                meta.get("metrics_baseline_payload_sha256")
            ),
            "payload_sha256_verified": bool(
                meta.get("metrics_baseline_payload_sha256_verified")
            ),
        },
        "runtime": {
            "report_generated_at_utc": _optional_str(
                meta.get("report_generated_at_utc")
            ),
            "scan_root_absolute": _optional_str(meta.get("scan_root")),
            "baseline_path_absolute": baseline_abs,
            "cache_path_absolute": cache_abs,
            "metrics_baseline_path_absolute": metrics_baseline_abs,
        },
    }


def _clone_group_assessment(
    *,
    count: int,
    clone_type: str,
) -> tuple[str, float]:
    match (count >= 4, clone_type in {"Type-1", "Type-2"}):
        case (True, _):
            severity = SEVERITY_CRITICAL
        case (False, True):
            severity = SEVERITY_WARNING
        case _:
            severity = SEVERITY_INFO
    effort = "easy" if clone_type in {"Type-1", "Type-2"} else "moderate"
    return severity, _priority(severity, effort)


def _build_clone_group_facts(
    *,
    group_key: str,
    kind: Literal["function", "block", "segment"],
    items: Sequence[GroupItemLike],
    block_facts: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, object], dict[str, str]]:
    base: dict[str, object] = {
        "group_key": group_key,
        "group_arity": len(items),
    }
    display_facts: dict[str, str] = {}
    match kind:
        case "function":
            loc_buckets = sorted(
                {
                    str(item.get("loc_bucket", ""))
                    for item in items
                    if str(item.get("loc_bucket", "")).strip()
                }
            )
            base["loc_buckets"] = loc_buckets
        case "block" if group_key in block_facts:
            typed_facts, block_display_facts = _normalize_block_machine_facts(
                group_key=group_key,
                group_arity=len(items),
                block_facts=block_facts[group_key],
            )
            base.update(typed_facts)
            display_facts.update(block_display_facts)
        case _:
            pass
    return base, display_facts


def _clone_item_payload(
    item: GroupItemLike,
    *,
    kind: Literal["function", "block", "segment"],
    scan_root: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "relative_path": _contract_report_location_path(
            str(item.get("filepath", "")),
            scan_root=scan_root,
        ),
        "qualname": str(item.get("qualname", "")),
        "start_line": _as_int(item.get("start_line", 0)),
        "end_line": _as_int(item.get("end_line", 0)),
    }
    match kind:
        case "function":
            payload.update(
                {
                    "loc": _as_int(item.get("loc", 0)),
                    "stmt_count": _as_int(item.get("stmt_count", 0)),
                    "fingerprint": str(item.get("fingerprint", "")),
                    "loc_bucket": str(item.get("loc_bucket", "")),
                    "cyclomatic_complexity": _as_int(
                        item.get("cyclomatic_complexity", 1)
                    ),
                    "nesting_depth": _as_int(item.get("nesting_depth", 0)),
                    "risk": str(item.get("risk", RISK_LOW)),
                    "raw_hash": str(item.get("raw_hash", "")),
                }
            )
        case "block":
            payload["size"] = _as_int(item.get("size", 0))
        case _:
            payload.update(
                {
                    "size": _as_int(item.get("size", 0)),
                    "segment_hash": str(item.get("segment_hash", "")),
                    "segment_sig": str(item.get("segment_sig", "")),
                }
            )
    return payload


def _build_clone_groups(
    *,
    groups: GroupMapLike,
    kind: Literal["function", "block", "segment"],
    baseline_trusted: bool,
    new_keys: Collection[str] | None,
    block_facts: Mapping[str, Mapping[str, str]],
    scan_root: str,
) -> list[dict[str, object]]:
    encoded_groups: list[dict[str, object]] = []
    new_key_set = set(new_keys) if new_keys is not None else None
    for group_key in sorted(groups):
        items = groups[group_key]
        clone_type = classify_clone_type(items=items, kind=kind)
        severity, priority = _clone_group_assessment(
            count=len(items),
            clone_type=clone_type,
        )
        novelty = _clone_novelty(
            group_key=group_key,
            baseline_trusted=baseline_trusted,
            new_keys=new_key_set,
        )
        locations = tuple(
            report_location_from_group_item(item, scan_root=scan_root) for item in items
        )
        source_scope = _source_scope_from_locations(
            [
                {
                    "source_kind": location.source_kind,
                }
                for location in locations
            ]
        )
        spread_files, spread_functions = group_spread(locations)
        rows = sorted(
            [
                _clone_item_payload(
                    item,
                    kind=kind,
                    scan_root=scan_root,
                )
                for item in items
            ],
            key=_item_sort_key,
        )
        facts, display_facts = _build_clone_group_facts(
            group_key=group_key,
            kind=kind,
            items=items,
            block_facts=block_facts,
        )
        encoded_groups.append(
            {
                "id": clone_group_id(kind, group_key),
                "family": FAMILY_CLONE,
                "category": kind,
                "kind": "clone_group",
                "severity": severity,
                "confidence": CONFIDENCE_HIGH,
                "priority": priority,
                "clone_kind": kind,
                "clone_type": clone_type,
                "novelty": novelty,
                "count": len(items),
                "source_scope": source_scope,
                "spread": {
                    "files": spread_files,
                    "functions": spread_functions,
                },
                "items": rows,
                "facts": facts,
                **({"display_facts": display_facts} if display_facts else {}),
            }
        )
    encoded_groups.sort(
        key=lambda group: (-_as_int(group.get("count")), str(group["id"]))
    )
    return encoded_groups


def _structural_group_assessment(
    *,
    finding_kind: str,
    count: int,
    spread_functions: int,
) -> tuple[str, float]:
    match finding_kind:
        case "clone_guard_exit_divergence" | "clone_cohort_drift":
            severity = SEVERITY_WARNING
            if count >= 3 or spread_functions > 1:
                severity = SEVERITY_CRITICAL
            return severity, _priority(severity, "moderate")
        case _:
            severity = (
                SEVERITY_WARNING
                if count >= 4 or spread_functions > 1
                else SEVERITY_INFO
            )
            return severity, _priority(severity, "moderate")


def _csv_values(value: object) -> list[str]:
    raw = str(value).strip()
    if not raw:
        return []
    return sorted({part.strip() for part in raw.split(",") if part.strip()})


def _build_structural_signature(
    finding_kind: str,
    signature: Mapping[str, str],
) -> dict[str, object]:
    debug = {str(key): str(signature[key]) for key in sorted(signature)}
    match finding_kind:
        case "clone_guard_exit_divergence":
            return {
                "version": "1",
                "stable": {
                    "family": "clone_guard_exit_divergence",
                    "cohort_id": str(signature.get("cohort_id", "")),
                    "majority_guard_count": _as_int(
                        signature.get("majority_guard_count")
                    ),
                    "majority_guard_terminal_profile": str(
                        signature.get("majority_guard_terminal_profile", "none")
                    ),
                    "majority_terminal_kind": str(
                        signature.get("majority_terminal_kind", "fallthrough")
                    ),
                    "majority_side_effect_before_guard": (
                        str(signature.get("majority_side_effect_before_guard", "0"))
                        == "1"
                    ),
                },
                "debug": debug,
            }
        case "clone_cohort_drift":
            return {
                "version": "1",
                "stable": {
                    "family": "clone_cohort_drift",
                    "cohort_id": str(signature.get("cohort_id", "")),
                    "drift_fields": _csv_values(signature.get("drift_fields")),
                    "majority_profile": {
                        "terminal_kind": str(
                            signature.get("majority_terminal_kind", "")
                        ),
                        "guard_exit_profile": str(
                            signature.get("majority_guard_exit_profile", "")
                        ),
                        "try_finally_profile": str(
                            signature.get("majority_try_finally_profile", "")
                        ),
                        "side_effect_order_profile": str(
                            signature.get("majority_side_effect_order_profile", "")
                        ),
                    },
                },
                "debug": debug,
            }
        case _:
            return {
                "version": "1",
                "stable": {
                    "family": "duplicated_branches",
                    "stmt_shape": str(signature.get("stmt_seq", "")),
                    "terminal_kind": str(signature.get("terminal", "")),
                    "control_flow": {
                        "has_loop": str(signature.get("has_loop", "0")) == "1",
                        "has_try": str(signature.get("has_try", "0")) == "1",
                        "nested_if": str(signature.get("nested_if", "0")) == "1",
                    },
                },
                "debug": debug,
            }


def _build_structural_facts(
    finding_kind: str,
    signature: Mapping[str, str],
    *,
    count: int,
) -> dict[str, object]:
    match finding_kind:
        case "clone_guard_exit_divergence":
            return {
                "cohort_id": str(signature.get("cohort_id", "")),
                "cohort_arity": _as_int(signature.get("cohort_arity")),
                "divergent_members": _as_int(signature.get("divergent_members"), count),
                "majority_entry_guard_count": _as_int(
                    signature.get("majority_guard_count"),
                ),
                "majority_guard_terminal_profile": str(
                    signature.get("majority_guard_terminal_profile", "none")
                ),
                "majority_terminal_kind": str(
                    signature.get("majority_terminal_kind", "fallthrough")
                ),
                "majority_side_effect_before_guard": (
                    str(signature.get("majority_side_effect_before_guard", "0")) == "1"
                ),
                "guard_count_values": _csv_values(signature.get("guard_count_values")),
                "guard_terminal_values": _csv_values(
                    signature.get("guard_terminal_values"),
                ),
                "terminal_values": _csv_values(signature.get("terminal_values")),
                "side_effect_before_guard_values": _csv_values(
                    signature.get("side_effect_before_guard_values"),
                ),
            }
        case "clone_cohort_drift":
            return {
                "cohort_id": str(signature.get("cohort_id", "")),
                "cohort_arity": _as_int(signature.get("cohort_arity")),
                "divergent_members": _as_int(signature.get("divergent_members"), count),
                "drift_fields": _csv_values(signature.get("drift_fields")),
                "stable_majority_profile": {
                    "terminal_kind": str(signature.get("majority_terminal_kind", "")),
                    "guard_exit_profile": str(
                        signature.get("majority_guard_exit_profile", "")
                    ),
                    "try_finally_profile": str(
                        signature.get("majority_try_finally_profile", "")
                    ),
                    "side_effect_order_profile": str(
                        signature.get("majority_side_effect_order_profile", "")
                    ),
                },
            }
        case _:
            return {
                "occurrence_count": count,
                "non_overlapping": True,
                "call_bucket": _as_int(signature.get("calls", "0")),
                "raise_bucket": _as_int(signature.get("raises", "0")),
            }


def _build_structural_groups(
    groups: Sequence[StructuralFindingGroup] | None,
    *,
    scan_root: str,
) -> list[dict[str, object]]:
    normalized_groups = normalize_structural_findings(groups or ())
    out: list[dict[str, object]] = []
    for group in normalized_groups:
        locations = tuple(
            report_location_from_structural_occurrence(item, scan_root=scan_root)
            for item in group.items
        )
        source_scope = _source_scope_from_locations(
            [{"source_kind": location.source_kind} for location in locations]
        )
        spread_files, spread_functions = group_spread(locations)
        severity, priority = _structural_group_assessment(
            finding_kind=group.finding_kind,
            count=len(group.items),
            spread_functions=spread_functions,
        )
        out.append(
            {
                "id": structural_group_id(group.finding_kind, group.finding_key),
                "family": FAMILY_STRUCTURAL,
                "category": group.finding_kind,
                "kind": group.finding_kind,
                "severity": severity,
                "confidence": (
                    CONFIDENCE_HIGH
                    if group.finding_kind
                    in {"clone_guard_exit_divergence", "clone_cohort_drift"}
                    else CONFIDENCE_MEDIUM
                ),
                "priority": priority,
                "count": len(group.items),
                "source_scope": source_scope,
                "spread": {
                    "files": spread_files,
                    "functions": spread_functions,
                },
                "signature": _build_structural_signature(
                    group.finding_kind,
                    group.signature,
                ),
                "items": sorted(
                    [
                        {
                            "relative_path": _contract_report_location_path(
                                item.file_path,
                                scan_root=scan_root,
                            ),
                            "qualname": item.qualname,
                            "start_line": item.start,
                            "end_line": item.end,
                        }
                        for item in group.items
                    ],
                    key=_item_sort_key,
                ),
                "facts": _build_structural_facts(
                    group.finding_kind,
                    group.signature,
                    count=len(group.items),
                ),
            }
        )
    out.sort(key=lambda group: (-_as_int(group.get("count")), str(group["id"])))
    return out


def _single_location_source_scope(
    filepath: str,
    *,
    scan_root: str,
) -> dict[str, object]:
    location = report_location_from_group_item(
        {
            "filepath": filepath,
            "qualname": "",
            "start_line": 0,
            "end_line": 0,
        },
        scan_root=scan_root,
    )
    return _source_scope_from_locations([{"source_kind": location.source_kind}])


def _build_dead_code_groups(
    metrics_payload: Mapping[str, object],
    *,
    scan_root: str,
) -> list[dict[str, object]]:
    families = _as_mapping(metrics_payload.get("families"))
    dead_code = _as_mapping(families.get(FAMILY_DEAD_CODE))
    groups: list[dict[str, object]] = []
    for item in _as_sequence(dead_code.get("items")):
        item_map = _as_mapping(item)
        qualname = str(item_map.get("qualname", ""))
        filepath = str(item_map.get("relative_path", ""))
        confidence = str(item_map.get("confidence", CONFIDENCE_MEDIUM))
        severity = SEVERITY_WARNING if confidence == CONFIDENCE_HIGH else SEVERITY_INFO
        groups.append(
            {
                "id": dead_code_group_id(qualname),
                "family": FAMILY_DEAD_CODE,
                "category": str(item_map.get("kind", "unknown")),
                "kind": "unused_symbol",
                "severity": severity,
                "confidence": confidence,
                "priority": _priority(severity, EFFORT_EASY),
                "count": 1,
                "source_scope": _single_location_source_scope(
                    filepath,
                    scan_root=scan_root,
                ),
                "spread": {"files": 1, "functions": 1 if qualname else 0},
                "items": [
                    {
                        "relative_path": _contract_report_location_path(
                            filepath,
                            scan_root=scan_root,
                        ),
                        "qualname": qualname,
                        "start_line": _as_int(item_map.get("start_line")),
                        "end_line": _as_int(item_map.get("end_line")),
                    }
                ],
                "facts": {
                    "kind": str(item_map.get("kind", "unknown")),
                    "confidence": confidence,
                },
            }
        )
    groups.sort(key=lambda group: (-_as_float(group["priority"]), str(group["id"])))
    return groups


def _build_design_groups(
    metrics_payload: Mapping[str, object],
    *,
    scan_root: str,
) -> list[dict[str, object]]:
    families = _as_mapping(metrics_payload.get("families"))
    groups: list[dict[str, object]] = []

    complexity = _as_mapping(families.get(CATEGORY_COMPLEXITY))
    for item in _as_sequence(complexity.get("items")):
        item_map = _as_mapping(item)
        cc = _as_int(item_map.get("cyclomatic_complexity"), 1)
        if cc <= 20:
            continue
        qualname = str(item_map.get("qualname", ""))
        filepath = str(item_map.get("relative_path", ""))
        severity = SEVERITY_CRITICAL if cc > 40 else SEVERITY_WARNING
        groups.append(
            {
                "id": design_group_id(CATEGORY_COMPLEXITY, qualname),
                "family": FAMILY_DESIGN,
                "category": CATEGORY_COMPLEXITY,
                "kind": "function_hotspot",
                "severity": severity,
                "confidence": CONFIDENCE_HIGH,
                "priority": _priority(severity, EFFORT_MODERATE),
                "count": 1,
                "source_scope": _single_location_source_scope(
                    filepath,
                    scan_root=scan_root,
                ),
                "spread": {"files": 1, "functions": 1},
                "items": [
                    {
                        "relative_path": _contract_report_location_path(
                            filepath,
                            scan_root=scan_root,
                        ),
                        "qualname": qualname,
                        "start_line": _as_int(item_map.get("start_line")),
                        "end_line": _as_int(item_map.get("end_line")),
                        "cyclomatic_complexity": cc,
                        "nesting_depth": _as_int(item_map.get("nesting_depth")),
                        "risk": str(item_map.get("risk", RISK_LOW)),
                    }
                ],
                "facts": {
                    "cyclomatic_complexity": cc,
                    "nesting_depth": _as_int(item_map.get("nesting_depth")),
                },
            }
        )

    coupling = _as_mapping(families.get(CATEGORY_COUPLING))
    for item in _as_sequence(coupling.get("items")):
        item_map = _as_mapping(item)
        cbo = _as_int(item_map.get("cbo"))
        if cbo <= 10:
            continue
        qualname = str(item_map.get("qualname", ""))
        filepath = str(item_map.get("relative_path", ""))
        groups.append(
            {
                "id": design_group_id(CATEGORY_COUPLING, qualname),
                "family": FAMILY_DESIGN,
                "category": CATEGORY_COUPLING,
                "kind": "class_hotspot",
                "severity": SEVERITY_WARNING,
                "confidence": CONFIDENCE_HIGH,
                "priority": _priority(SEVERITY_WARNING, EFFORT_MODERATE),
                "count": 1,
                "source_scope": _single_location_source_scope(
                    filepath,
                    scan_root=scan_root,
                ),
                "spread": {"files": 1, "functions": 1},
                "items": [
                    {
                        "relative_path": _contract_report_location_path(
                            filepath,
                            scan_root=scan_root,
                        ),
                        "qualname": qualname,
                        "start_line": _as_int(item_map.get("start_line")),
                        "end_line": _as_int(item_map.get("end_line")),
                        "cbo": cbo,
                        "risk": str(item_map.get("risk", RISK_LOW)),
                        "coupled_classes": list(
                            _as_sequence(item_map.get("coupled_classes"))
                        ),
                    }
                ],
                "facts": {
                    "cbo": cbo,
                    "coupled_classes": list(
                        _as_sequence(item_map.get("coupled_classes"))
                    ),
                },
            }
        )

    cohesion = _as_mapping(families.get(CATEGORY_COHESION))
    for item in _as_sequence(cohesion.get("items")):
        item_map = _as_mapping(item)
        lcom4 = _as_int(item_map.get("lcom4"))
        if lcom4 <= 3:
            continue
        qualname = str(item_map.get("qualname", ""))
        filepath = str(item_map.get("relative_path", ""))
        groups.append(
            {
                "id": design_group_id(CATEGORY_COHESION, qualname),
                "family": FAMILY_DESIGN,
                "category": CATEGORY_COHESION,
                "kind": "class_hotspot",
                "severity": SEVERITY_WARNING,
                "confidence": CONFIDENCE_HIGH,
                "priority": _priority(SEVERITY_WARNING, EFFORT_MODERATE),
                "count": 1,
                "source_scope": _single_location_source_scope(
                    filepath,
                    scan_root=scan_root,
                ),
                "spread": {"files": 1, "functions": 1},
                "items": [
                    {
                        "relative_path": _contract_report_location_path(
                            filepath,
                            scan_root=scan_root,
                        ),
                        "qualname": qualname,
                        "start_line": _as_int(item_map.get("start_line")),
                        "end_line": _as_int(item_map.get("end_line")),
                        "lcom4": lcom4,
                        "risk": str(item_map.get("risk", RISK_LOW)),
                        "method_count": _as_int(item_map.get("method_count")),
                        "instance_var_count": _as_int(
                            item_map.get("instance_var_count")
                        ),
                    }
                ],
                "facts": {
                    "lcom4": lcom4,
                    "method_count": _as_int(item_map.get("method_count")),
                    "instance_var_count": _as_int(item_map.get("instance_var_count")),
                },
            }
        )

    dependencies = _as_mapping(families.get("dependencies"))
    for cycle in _as_sequence(dependencies.get("cycles")):
        modules = [str(module) for module in _as_sequence(cycle) if str(module).strip()]
        if not modules:
            continue
        cycle_key = " -> ".join(modules)
        source_scope = _source_scope_from_filepaths(
            (module.replace(".", "/") + ".py" for module in modules),
            scan_root=scan_root,
        )
        groups.append(
            {
                "id": design_group_id(CATEGORY_DEPENDENCY, cycle_key),
                "family": FAMILY_DESIGN,
                "category": CATEGORY_DEPENDENCY,
                "kind": "cycle",
                "severity": SEVERITY_CRITICAL,
                "confidence": CONFIDENCE_HIGH,
                "priority": _priority(SEVERITY_CRITICAL, EFFORT_HARD),
                "count": len(modules),
                "source_scope": source_scope,
                "spread": {"files": len(modules), "functions": 0},
                "items": [
                    {
                        "module": module,
                        "relative_path": module.replace(".", "/") + ".py",
                        "source_kind": report_location_from_group_item(
                            {
                                "filepath": module.replace(".", "/") + ".py",
                                "qualname": "",
                                "start_line": 0,
                                "end_line": 0,
                            }
                        ).source_kind,
                    }
                    for module in modules
                ],
                "facts": {
                    "cycle_length": len(modules),
                },
            }
        )

    groups.sort(key=lambda group: (-_as_float(group["priority"]), str(group["id"])))
    return groups


def _findings_summary(
    *,
    clone_functions: Sequence[Mapping[str, object]],
    clone_blocks: Sequence[Mapping[str, object]],
    clone_segments: Sequence[Mapping[str, object]],
    structural_groups: Sequence[Mapping[str, object]],
    dead_code_groups: Sequence[Mapping[str, object]],
    design_groups: Sequence[Mapping[str, object]],
    dead_code_suppressed: int = 0,
) -> dict[str, object]:
    flat_groups = [
        *clone_functions,
        *clone_blocks,
        *clone_segments,
        *structural_groups,
        *dead_code_groups,
        *design_groups,
    ]
    severity_counts = dict.fromkeys(
        (SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO),
        0,
    )
    source_scope_counts = dict.fromkeys(
        (IMPACT_SCOPE_RUNTIME, IMPACT_SCOPE_NON_RUNTIME, IMPACT_SCOPE_MIXED),
        0,
    )
    for group in flat_groups:
        severity = str(group.get("severity", SEVERITY_INFO))
        if severity in severity_counts:
            severity_counts[severity] += 1
        impact_scope = str(
            _as_mapping(group.get("source_scope")).get(
                "impact_scope",
                IMPACT_SCOPE_NON_RUNTIME,
            )
        )
        if impact_scope in source_scope_counts:
            source_scope_counts[impact_scope] += 1
    clone_groups = [*clone_functions, *clone_blocks, *clone_segments]
    return {
        "total": len(flat_groups),
        "families": {
            FAMILY_CLONES: len(clone_groups),
            FAMILY_STRUCTURAL: len(structural_groups),
            FAMILY_DEAD_CODE: len(dead_code_groups),
            "design": len(design_groups),
        },
        "severity": severity_counts,
        "impact_scope": source_scope_counts,
        "clones": {
            "functions": len(clone_functions),
            "blocks": len(clone_blocks),
            "segments": len(clone_segments),
            CLONE_NOVELTY_NEW: sum(
                1
                for group in clone_groups
                if str(group.get("novelty", "")) == CLONE_NOVELTY_NEW
            ),
            CLONE_NOVELTY_KNOWN: sum(
                1
                for group in clone_groups
                if str(group.get("novelty", "")) == CLONE_NOVELTY_KNOWN
            ),
        },
        "suppressed": {
            FAMILY_DEAD_CODE: max(0, dead_code_suppressed),
        },
    }


def _sort_flat_finding_ids(
    groups: Sequence[Mapping[str, object]],
) -> list[str]:
    ordered = sorted(
        groups,
        key=lambda group: (
            -_as_float(group.get("priority")),
            SEVERITY_ORDER.get(str(group.get("severity", SEVERITY_INFO)), 9),
            -_as_int(_as_mapping(group.get("spread")).get("files")),
            -_as_int(_as_mapping(group.get("spread")).get("functions")),
            -_as_int(group.get("count")),
            str(group.get("id", "")),
        ),
    )
    return [str(group["id"]) for group in ordered]


def _sort_highest_spread_ids(
    groups: Sequence[Mapping[str, object]],
) -> list[str]:
    ordered = sorted(
        groups,
        key=lambda group: (
            -_as_int(_as_mapping(group.get("spread")).get("files")),
            -_as_int(_as_mapping(group.get("spread")).get("functions")),
            -_as_int(group.get("count")),
            -_as_float(group.get("priority")),
            str(group.get("id", "")),
        ),
    )
    return [str(group["id"]) for group in ordered]


def _health_snapshot(metrics_payload: Mapping[str, object]) -> dict[str, object]:
    health = _as_mapping(_as_mapping(metrics_payload.get("families")).get("health"))
    summary = _as_mapping(health.get("summary"))
    dimensions = {
        str(key): _as_int(value)
        for key, value in _as_mapping(summary.get("dimensions")).items()
    }
    strongest = None
    weakest = None
    if dimensions:
        strongest = min(
            sorted(dimensions),
            key=lambda key: (-dimensions[key], key),
        )
        weakest = min(
            sorted(dimensions),
            key=lambda key: (dimensions[key], key),
        )
    return {
        "score": _as_int(summary.get("score")),
        "grade": str(summary.get("grade", "")),
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
    }


def _combined_impact_scope(groups: Sequence[Mapping[str, object]]) -> str:
    impact_scopes = {
        str(
            _as_mapping(group.get("source_scope")).get(
                "impact_scope",
                IMPACT_SCOPE_NON_RUNTIME,
            )
        )
        for group in groups
    }
    if not impact_scopes:
        return IMPACT_SCOPE_NON_RUNTIME
    if len(impact_scopes) == 1:
        return next(iter(impact_scopes))
    return IMPACT_SCOPE_MIXED


def _top_risks(
    *,
    dead_code_groups: Sequence[Mapping[str, object]],
    design_groups: Sequence[Mapping[str, object]],
    structural_groups: Sequence[Mapping[str, object]],
    clone_groups: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    risks: list[dict[str, object]] = []

    if dead_code_groups:
        label = (
            "1 dead code item"
            if len(dead_code_groups) == 1
            else f"{len(dead_code_groups)} dead code items"
        )
        risks.append(
            {
                "kind": "family_summary",
                "family": FAMILY_DEAD_CODE,
                "count": len(dead_code_groups),
                "scope": IMPACT_SCOPE_MIXED
                if len(
                    {
                        _as_mapping(group.get("source_scope")).get("impact_scope")
                        for group in dead_code_groups
                    }
                )
                > 1
                else str(
                    _as_mapping(dead_code_groups[0].get("source_scope")).get(
                        "impact_scope",
                        IMPACT_SCOPE_NON_RUNTIME,
                    )
                ),
                "label": label,
            }
        )

    low_cohesion = [
        group
        for group in design_groups
        if str(group.get("category", "")) == CATEGORY_COHESION
    ]
    if low_cohesion:
        label = (
            "1 low cohesion class"
            if len(low_cohesion) == 1
            else f"{len(low_cohesion)} low cohesion classes"
        )
        risks.append(
            {
                "kind": "family_summary",
                "family": FAMILY_DESIGN,
                "category": CATEGORY_COHESION,
                "count": len(low_cohesion),
                "scope": _combined_impact_scope(low_cohesion),
                "label": label,
            }
        )

    production_structural = [
        group
        for group in structural_groups
        if str(_as_mapping(group.get("source_scope")).get("impact_scope"))
        in {IMPACT_SCOPE_RUNTIME, IMPACT_SCOPE_MIXED}
    ]
    if production_structural:
        label = (
            "1 structural finding in production code"
            if len(production_structural) == 1
            else (
                f"{len(production_structural)} structural findings in production code"
            )
        )
        risks.append(
            {
                "kind": "family_summary",
                "family": FAMILY_STRUCTURAL,
                "count": len(production_structural),
                "scope": SOURCE_KIND_PRODUCTION,
                "label": label,
            }
        )

    fixture_test_clones = [
        group
        for group in clone_groups
        if _as_mapping(group.get("source_scope")).get("impact_scope")
        == IMPACT_SCOPE_NON_RUNTIME
        and _as_mapping(group.get("source_scope")).get("dominant_kind")
        in {SOURCE_KIND_TESTS, SOURCE_KIND_FIXTURES}
    ]
    if fixture_test_clones:
        label = (
            "1 clone group in fixtures/tests"
            if len(fixture_test_clones) == 1
            else f"{len(fixture_test_clones)} clone groups in fixtures/tests"
        )
        risks.append(
            {
                "kind": "family_summary",
                "family": FAMILY_CLONE,
                "count": len(fixture_test_clones),
                "scope": IMPACT_SCOPE_NON_RUNTIME,
                "label": label,
            }
        )

    return risks[:6]


def _build_derived_overview(
    *,
    findings: Mapping[str, object],
    metrics_payload: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    groups = _as_mapping(findings.get("groups"))
    clones = _as_mapping(groups.get(FAMILY_CLONES))
    clone_groups = [
        *_as_sequence(clones.get("functions")),
        *_as_sequence(clones.get("blocks")),
        *_as_sequence(clones.get("segments")),
    ]
    structural_groups = _as_sequence(
        _as_mapping(groups.get(FAMILY_STRUCTURAL)).get("groups")
    )
    dead_code_groups = _as_sequence(
        _as_mapping(groups.get(FAMILY_DEAD_CODE)).get("groups")
    )
    design_groups = _as_sequence(_as_mapping(groups.get("design")).get("groups"))
    flat_groups = [
        *clone_groups,
        *structural_groups,
        *dead_code_groups,
        *design_groups,
    ]
    dominant_kind_counts: Counter[str] = Counter(
        str(
            _as_mapping(_as_mapping(group).get("source_scope")).get(
                "dominant_kind",
                SOURCE_KIND_OTHER,
            )
        )
        for group in flat_groups
    )
    summary = _as_mapping(findings.get("summary"))
    overview: dict[str, object] = {
        "families": dict(_as_mapping(summary.get("families"))),
        "top_risks": _top_risks(
            dead_code_groups=[_as_mapping(group) for group in dead_code_groups],
            design_groups=[_as_mapping(group) for group in design_groups],
            structural_groups=[_as_mapping(group) for group in structural_groups],
            clone_groups=[_as_mapping(group) for group in clone_groups],
        ),
        "source_scope_breakdown": {
            key: dominant_kind_counts[key]
            for key in (
                SOURCE_KIND_PRODUCTION,
                SOURCE_KIND_TESTS,
                SOURCE_KIND_FIXTURES,
                SOURCE_KIND_MIXED,
                SOURCE_KIND_OTHER,
            )
            if dominant_kind_counts[key] > 0
        },
        "health_snapshot": _health_snapshot(metrics_payload),
    }
    hotlists: dict[str, object] = {
        "most_actionable_ids": _sort_flat_finding_ids(
            [
                group
                for group in map(_as_mapping, flat_groups)
                if str(group.get("severity")) != SEVERITY_INFO
            ]
        )[:5],
        "highest_spread_ids": _sort_highest_spread_ids(
            list(map(_as_mapping, flat_groups))
        )[:5],
        "production_hotspot_ids": _sort_flat_finding_ids(
            [
                group
                for group in map(_as_mapping, flat_groups)
                if str(_as_mapping(group.get("source_scope")).get("impact_scope"))
                in {IMPACT_SCOPE_RUNTIME, IMPACT_SCOPE_MIXED}
            ]
        )[:5],
        "test_fixture_hotspot_ids": _sort_flat_finding_ids(
            [
                group
                for group in map(_as_mapping, flat_groups)
                if str(_as_mapping(group.get("source_scope")).get("impact_scope"))
                == IMPACT_SCOPE_NON_RUNTIME
                and str(_as_mapping(group.get("source_scope")).get("dominant_kind"))
                in {SOURCE_KIND_TESTS, SOURCE_KIND_FIXTURES}
            ]
        )[:5],
    }
    return overview, hotlists


def _representative_location_rows(
    suggestion: Suggestion,
) -> list[dict[str, object]]:
    rows = [
        {
            "relative_path": (
                location.relative_path
                if (
                    location.relative_path
                    and not _is_absolute_path(location.relative_path)
                )
                else _contract_report_location_path(
                    location.filepath,
                    scan_root="",
                )
            ),
            "start_line": location.start_line,
            "end_line": location.end_line,
            "qualname": location.qualname,
            "source_kind": location.source_kind,
        }
        for location in suggestion.representative_locations
    ]
    rows.sort(
        key=lambda row: (
            str(row["relative_path"]),
            _as_int(row["start_line"]),
            _as_int(row["end_line"]),
            str(row["qualname"]),
        )
    )
    return rows[:3]


def _suggestion_finding_id(suggestion: Suggestion) -> str:
    if suggestion.finding_family == FAMILY_CLONES:
        if suggestion.fact_kind.startswith("Function"):
            return clone_group_id(CLONE_KIND_FUNCTION, suggestion.subject_key)
        if suggestion.fact_kind.startswith("Block"):
            return clone_group_id(CLONE_KIND_BLOCK, suggestion.subject_key)
        return clone_group_id(CLONE_KIND_SEGMENT, suggestion.subject_key)
    if suggestion.finding_family == FAMILY_STRUCTURAL:
        return structural_group_id(
            suggestion.finding_kind or "duplicated_branches",
            suggestion.subject_key,
        )
    if suggestion.category == CATEGORY_DEAD_CODE:
        return dead_code_group_id(suggestion.subject_key)
    if suggestion.category in {
        CATEGORY_COMPLEXITY,
        CATEGORY_COUPLING,
        CATEGORY_COHESION,
        CATEGORY_DEPENDENCY,
    }:
        return design_group_id(suggestion.category, suggestion.subject_key)
    return design_group_id(
        suggestion.category,
        suggestion.subject_key or suggestion.title,
    )


def _build_derived_suggestions(
    suggestions: Sequence[Suggestion] | None,
) -> list[dict[str, object]]:
    suggestion_rows = list(suggestions or ())
    suggestion_rows.sort(
        key=lambda suggestion: (
            -suggestion.priority,
            SEVERITY_ORDER.get(suggestion.severity, 9),
            suggestion.title,
            _suggestion_finding_id(suggestion),
        )
    )
    return [
        {
            "id": f"suggestion:{_suggestion_finding_id(suggestion)}",
            "finding_id": _suggestion_finding_id(suggestion),
            "title": suggestion.title,
            "summary": suggestion.fact_summary,
            "location_label": suggestion.location_label or suggestion.location,
            "representative_locations": _representative_location_rows(suggestion),
            "action": {
                "effort": suggestion.effort,
                "steps": list(suggestion.steps),
            },
        }
        for suggestion in suggestion_rows
    ]


def _build_findings_payload(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    block_facts: Mapping[str, Mapping[str, str]],
    structural_findings: Sequence[StructuralFindingGroup] | None,
    metrics_payload: Mapping[str, object],
    baseline_trusted: bool,
    new_function_group_keys: Collection[str] | None,
    new_block_group_keys: Collection[str] | None,
    new_segment_group_keys: Collection[str] | None,
    scan_root: str,
) -> dict[str, object]:
    clone_functions = _build_clone_groups(
        groups=func_groups,
        kind=CLONE_KIND_FUNCTION,
        baseline_trusted=baseline_trusted,
        new_keys=new_function_group_keys,
        block_facts=block_facts,
        scan_root=scan_root,
    )
    clone_blocks = _build_clone_groups(
        groups=block_groups,
        kind=CLONE_KIND_BLOCK,
        baseline_trusted=baseline_trusted,
        new_keys=new_block_group_keys,
        block_facts=block_facts,
        scan_root=scan_root,
    )
    clone_segments = _build_clone_groups(
        groups=segment_groups,
        kind=CLONE_KIND_SEGMENT,
        baseline_trusted=baseline_trusted,
        new_keys=new_segment_group_keys,
        block_facts={},
        scan_root=scan_root,
    )
    structural_groups = _build_structural_groups(
        structural_findings,
        scan_root=scan_root,
    )
    dead_code_groups = _build_dead_code_groups(
        metrics_payload,
        scan_root=scan_root,
    )
    dead_code_family = _as_mapping(
        _as_mapping(metrics_payload.get("families")).get(FAMILY_DEAD_CODE)
    )
    dead_code_summary = _as_mapping(dead_code_family.get("summary"))
    dead_code_suppressed = _as_int(
        dead_code_summary.get(
            "suppressed",
            len(_as_sequence(dead_code_family.get("suppressed_items"))),
        )
    )
    design_groups = _build_design_groups(
        metrics_payload,
        scan_root=scan_root,
    )
    return {
        "summary": _findings_summary(
            clone_functions=clone_functions,
            clone_blocks=clone_blocks,
            clone_segments=clone_segments,
            structural_groups=structural_groups,
            dead_code_groups=dead_code_groups,
            design_groups=design_groups,
            dead_code_suppressed=dead_code_suppressed,
        ),
        "groups": {
            FAMILY_CLONES: {
                "functions": clone_functions,
                "blocks": clone_blocks,
                "segments": clone_segments,
            },
            FAMILY_STRUCTURAL: {
                "groups": structural_groups,
            },
            FAMILY_DEAD_CODE: {
                "groups": dead_code_groups,
            },
            "design": {
                "groups": design_groups,
            },
        },
    }


def _canonical_integrity_payload(
    *,
    report_schema_version: str,
    meta: Mapping[str, object],
    inventory: Mapping[str, object],
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, object]:
    canonical_meta = {
        str(key): value for key, value in meta.items() if str(key) != "runtime"
    }

    def _strip_noncanonical(value: object) -> object:
        if isinstance(value, Mapping):
            return {
                str(key): _strip_noncanonical(item)
                for key, item in value.items()
                if str(key) != "display_facts"
            }
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            return [_strip_noncanonical(item) for item in value]
        return value

    return {
        "report_schema_version": report_schema_version,
        "meta": canonical_meta,
        "inventory": inventory,
        "findings": _strip_noncanonical(findings),
        "metrics": metrics,
    }


def _build_integrity_payload(
    *,
    report_schema_version: str,
    meta: Mapping[str, object],
    inventory: Mapping[str, object],
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, object]:
    canonical_payload = _canonical_integrity_payload(
        report_schema_version=report_schema_version,
        meta=meta,
        inventory=inventory,
        findings=findings,
        metrics=metrics,
    )
    canonical_json = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_sha = sha256(canonical_json).hexdigest()
    return {
        "canonicalization": {
            "version": "1",
            "scope": "canonical_only",
            "sections": [
                "report_schema_version",
                "meta",
                "inventory",
                "findings",
                "metrics",
            ],
        },
        "digest": {
            "verified": True,
            "algorithm": "sha256",
            "value": payload_sha,
        },
    }


def build_report_document(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    meta: Mapping[str, object] | None = None,
    inventory: Mapping[str, object] | None = None,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
) -> dict[str, object]:
    report_schema_version = REPORT_SCHEMA_VERSION
    scan_root = str(_as_mapping(meta).get("scan_root", ""))
    meta_payload = _build_meta_payload(meta, scan_root=scan_root)
    metrics_payload = _build_metrics_payload(metrics, scan_root=scan_root)
    file_list = _collect_report_file_list(
        inventory=inventory,
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        metrics=metrics,
        structural_findings=structural_findings,
    )
    inventory_payload = _build_inventory_payload(
        inventory=inventory,
        file_list=file_list,
        metrics_payload=metrics_payload,
        scan_root=scan_root,
    )
    findings_payload = _build_findings_payload(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        block_facts=block_facts or {},
        structural_findings=structural_findings,
        metrics_payload=metrics_payload,
        baseline_trusted=_baseline_is_trusted(meta_payload),
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        new_segment_group_keys=new_segment_group_keys,
        scan_root=scan_root,
    )
    overview_payload, hotlists_payload = _build_derived_overview(
        findings=findings_payload,
        metrics_payload=metrics_payload,
    )
    derived_payload = {
        "suggestions": _build_derived_suggestions(suggestions),
        "overview": overview_payload,
        "hotlists": hotlists_payload,
    }
    integrity_payload = _build_integrity_payload(
        report_schema_version=report_schema_version,
        meta=meta_payload,
        inventory=inventory_payload,
        findings=findings_payload,
        metrics=metrics_payload,
    )
    return {
        "report_schema_version": report_schema_version,
        "meta": meta_payload,
        "inventory": inventory_payload,
        "findings": findings_payload,
        "metrics": metrics_payload,
        "derived": derived_payload,
        "integrity": integrity_payload,
    }
