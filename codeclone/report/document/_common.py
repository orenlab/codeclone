# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

from ...contracts import (
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
)
from ...domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CLONE_NOVELTY_KNOWN,
    CLONE_NOVELTY_NEW,
    FAMILY_DEAD_CODE,
)
from ...domain.quality import (
    EFFORT_WEIGHT,
    SEVERITY_RANK,
)
from ...findings.structural.detectors import normalize_structural_findings
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..derived import (
    normalized_source_kind as _normalized_source_kind,
)
from ..derived import (
    relative_report_path,
    report_location_from_group_item,
)
from ..derived import (
    source_scope_from_counts as _report_source_scope_from_counts,
)
from ..derived import (
    source_scope_from_locations as _report_source_scope_from_locations,
)

if TYPE_CHECKING:
    from ...models import (
        GroupMapLike,
        SourceKind,
        StructuralFindingGroup,
        SuppressedCloneGroup,
    )

_OVERLOADED_MODULES_FAMILY = "overloaded_modules"
_COVERAGE_ADOPTION_FAMILY = "coverage_adoption"
_API_SURFACE_FAMILY = "api_surface"
_COVERAGE_JOIN_FAMILY = "coverage_join"
_SECURITY_SURFACES_FAMILY = "security_surfaces"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerced_nonnegative_threshold(value: object, *, default: int) -> int:
    threshold = _as_int(value, default)
    return threshold if threshold >= 0 else default


def _design_findings_thresholds_payload(
    raw_meta: Mapping[str, object] | None,
) -> dict[str, object]:
    meta = dict(raw_meta or {})
    return {
        "design_findings": {
            CATEGORY_COMPLEXITY: {
                "metric": "cyclomatic_complexity",
                "operator": ">",
                "value": _coerced_nonnegative_threshold(
                    meta.get("design_complexity_threshold"),
                    default=DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
                ),
            },
            CATEGORY_COUPLING: {
                "metric": "cbo",
                "operator": ">",
                "value": _coerced_nonnegative_threshold(
                    meta.get("design_coupling_threshold"),
                    default=DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
                ),
            },
            CATEGORY_COHESION: {
                "metric": "lcom4",
                "operator": ">=",
                "value": _coerced_nonnegative_threshold(
                    meta.get("design_cohesion_threshold"),
                    default=DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
                ),
            },
        }
    }


def _analysis_profile_payload(
    raw_meta: Mapping[str, object] | None,
) -> dict[str, int] | None:
    meta = dict(raw_meta or {})
    nested = _as_mapping(meta.get("analysis_profile"))
    if nested:
        meta = dict(nested)
    keys = (
        "min_loc",
        "min_stmt",
        "block_min_loc",
        "block_min_stmt",
        "segment_min_loc",
        "segment_min_stmt",
    )
    if any(key not in meta for key in keys):
        return None
    payload = {key: _as_int(meta.get(key), -1) for key in keys}
    if any(value < 0 for value in payload.values()):
        return None
    return payload


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
    return _source_scope_from_counts(counts)


def _source_scope_from_counts(
    counts: Mapping[SourceKind, int],
) -> dict[str, object]:
    return _report_source_scope_from_counts(counts)


def _source_scope_from_locations(
    locations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    normalized_locations = [
        {"source_kind": _normalized_source_kind(location.get("source_kind"))}
        for location in locations
    ]
    return _report_source_scope_from_locations(normalized_locations)


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
    overloaded_modules = _as_mapping(metrics.get(_OVERLOADED_MODULES_FAMILY))
    for item in _as_sequence(overloaded_modules.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    coverage_adoption = _as_mapping(metrics.get(_COVERAGE_ADOPTION_FAMILY))
    for item in _as_sequence(coverage_adoption.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    api_surface = _as_mapping(metrics.get(_API_SURFACE_FAMILY))
    for item in _as_sequence(api_surface.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    coverage_join = _as_mapping(metrics.get(_COVERAGE_JOIN_FAMILY))
    for item in _as_sequence(coverage_join.get("items")):
        item_map = _as_mapping(item)
        filepath = _optional_str(item_map.get("filepath"))
        if filepath is not None:
            paths.add(filepath)
    security_surfaces = _as_mapping(metrics.get(_SECURITY_SURFACES_FAMILY))
    for item in _as_sequence(security_surfaces.get("items")):
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
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
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
    for suppressed_group in suppressed_clone_groups or ():
        for item in suppressed_group.items:
            filepath = _optional_str(item.get("filepath"))
            if filepath is not None:
                files.add(filepath)
    if metrics is not None:
        files.update(_collect_paths_from_metrics(metrics))
    if structural_findings:
        for structural_group in normalize_structural_findings(structural_findings):
            for occurrence in structural_group.items:
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


__all__ = [
    "_collect_report_file_list",
    "normalize_structural_findings",
]
