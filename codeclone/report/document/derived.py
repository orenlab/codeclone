# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from ...domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    FAMILY_CLONE,
    FAMILY_CLONES,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_STRUCTURAL,
)
from ...domain.quality import (
    SEVERITY_INFO,
    SEVERITY_ORDER,
)
from ...domain.source_scope import (
    IMPACT_SCOPE_MIXED,
    IMPACT_SCOPE_NON_RUNTIME,
    IMPACT_SCOPE_RUNTIME,
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_MIXED,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from ...findings.ids import (
    clone_group_id,
    dead_code_group_id,
    design_group_id,
    structural_group_id,
)
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..overview import build_directory_hotspots
from ._common import _contract_report_location_path, _is_absolute_path

if TYPE_CHECKING:
    from ...models import (
        Suggestion,
    )


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
        "directory_hotspots": build_directory_hotspots(findings=findings),
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
