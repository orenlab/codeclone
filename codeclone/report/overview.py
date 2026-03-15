# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Suggestion

__all__ = ["build_report_overview", "serialize_suggestion_card"]


def serialize_suggestion_card(suggestion: Suggestion) -> dict[str, object]:
    return {
        "title": suggestion.title,
        "family": suggestion.finding_family,
        "category": suggestion.category,
        "summary": suggestion.fact_summary,
        "severity": suggestion.severity,
        "priority": suggestion.priority,
        "confidence": suggestion.confidence,
        "source_kind": suggestion.source_kind,
        "location": suggestion.location_label or suggestion.location,
        "clone_type": suggestion.clone_type,
        "count": suggestion.fact_count,
        "spread": {
            "files": suggestion.spread_files,
            "functions": suggestion.spread_functions,
        },
    }


def _card_key(suggestion: Suggestion) -> tuple[float, int, int, int, str, str]:
    return (
        -suggestion.priority,
        -suggestion.spread_files,
        -suggestion.spread_functions,
        -suggestion.fact_count,
        suggestion.location_label or suggestion.location,
        suggestion.title,
    )


def _spread_key(suggestion: Suggestion) -> tuple[int, int, int, float, str]:
    return (
        -suggestion.spread_files,
        -suggestion.spread_functions,
        -suggestion.fact_count,
        -suggestion.priority,
        suggestion.title,
    )


def _source_counts(
    suggestions: Sequence[Suggestion],
) -> dict[str, int]:
    counts: Counter[str] = Counter(suggestion.source_kind for suggestion in suggestions)
    ordered_kinds = ("production", "tests", "fixtures", "mixed", "other")
    return {kind: counts[kind] for kind in ordered_kinds if counts[kind] > 0} | {
        kind: counts[kind]
        for kind in sorted(counts)
        if kind not in ordered_kinds and counts[kind] > 0
    }


def _health_snapshot(metrics: Mapping[str, object]) -> dict[str, object]:
    health = metrics.get("health")
    if not isinstance(health, Mapping):
        return {}
    dimensions = health.get("dimensions")
    if not isinstance(dimensions, Mapping):
        return {
            "score": health.get("score"),
            "grade": health.get("grade"),
            "strongest_dimension": None,
            "weakest_dimension": None,
        }
    normalized_dimensions = {
        str(key): int(value)
        for key, value in dimensions.items()
        if isinstance(key, str) and isinstance(value, int)
    }
    strongest = None
    weakest = None
    if normalized_dimensions:
        strongest = min(
            sorted(normalized_dimensions),
            key=lambda key: (-normalized_dimensions[key], key),
        )
        weakest = min(
            sorted(normalized_dimensions),
            key=lambda key: (normalized_dimensions[key], key),
        )
    return {
        "score": health.get("score"),
        "grade": health.get("grade"),
        "strongest_dimension": strongest,
        "weakest_dimension": weakest,
    }


def _top_risks(
    suggestions: Sequence[Suggestion],
    *,
    metrics: Mapping[str, object],
) -> list[str]:
    risks: list[str] = []
    dead_code_map = metrics.get("dead_code")
    if isinstance(dead_code_map, Mapping):
        summary = dead_code_map.get("summary")
        if isinstance(summary, Mapping):
            high_conf = int(summary.get("critical", 0))
            if high_conf > 0:
                noun = "item" if high_conf == 1 else "items"
                risks.append(f"{high_conf} dead code {noun}")
    cohesion_map = metrics.get("cohesion")
    if isinstance(cohesion_map, Mapping):
        summary = cohesion_map.get("summary")
        if isinstance(summary, Mapping):
            low = int(summary.get("low_cohesion", 0))
            if low > 0:
                noun = "class" if low == 1 else "classes"
                risks.append(f"{low} low cohesion {noun}")
    production_structural = sum(
        1
        for suggestion in suggestions
        if suggestion.finding_family == "structural"
        and suggestion.source_kind == "production"
    )
    if production_structural > 0:
        noun = "finding" if production_structural == 1 else "findings"
        risks.append(f"{production_structural} structural {noun} in production code")
    test_clone_groups = sum(
        1
        for suggestion in suggestions
        if suggestion.finding_family == "clones"
        and suggestion.source_kind in {"tests", "fixtures"}
    )
    if test_clone_groups > 0:
        noun = "group" if test_clone_groups == 1 else "groups"
        risks.append(f"{test_clone_groups} clone {noun} in tests/fixtures")
    return risks[:6]


def build_report_overview(
    *,
    suggestions: Sequence[Suggestion],
    metrics: Mapping[str, object] | None = None,
) -> dict[str, object]:
    metrics_map = metrics if isinstance(metrics, Mapping) else {}
    metrics_suggestions = tuple(
        suggestion
        for suggestion in suggestions
        if suggestion.finding_family == "metrics" and suggestion.category != "dead_code"
    )
    actionable = tuple(
        suggestion for suggestion in suggestions if suggestion.severity != "info"
    )
    highest_spread = tuple(sorted(suggestions, key=_spread_key))[:5]
    production_hotspots = tuple(
        sorted(
            (
                suggestion
                for suggestion in suggestions
                if suggestion.source_kind == "production"
            ),
            key=_card_key,
        )
    )[:5]
    test_fixture_hotspots = tuple(
        sorted(
            (
                suggestion
                for suggestion in suggestions
                if suggestion.source_kind in {"tests", "fixtures"}
            ),
            key=_card_key,
        )
    )[:5]
    return {
        "families": {
            "clone_groups": sum(
                1 for suggestion in suggestions if suggestion.finding_family == "clones"
            ),
            "structural_findings": sum(
                1
                for suggestion in suggestions
                if suggestion.finding_family == "structural"
            ),
            "dead_code": sum(
                1 for suggestion in suggestions if suggestion.category == "dead_code"
            ),
            "metric_hotspots": len(metrics_suggestions),
        },
        "top_risks": _top_risks(suggestions, metrics=metrics_map),
        "health": _health_snapshot(metrics_map),
        "source_breakdown": _source_counts(suggestions),
        "most_actionable": [
            serialize_suggestion_card(suggestion)
            for suggestion in tuple(sorted(actionable, key=_card_key))[:5]
        ],
        "highest_spread": [
            serialize_suggestion_card(suggestion) for suggestion in highest_spread
        ],
        "production_hotspots": [
            serialize_suggestion_card(suggestion) for suggestion in production_hotspots
        ],
        "test_fixture_hotspots": [
            serialize_suggestion_card(suggestion)
            for suggestion in test_fixture_hotspots
        ],
    }
