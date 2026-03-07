"""Suggestion engine and clone type classification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from ..models import ClassMetrics, GroupItemLike, ProjectMetrics, Suggestion

Severity = Literal["critical", "warning", "info"]
Effort = Literal["easy", "moderate", "hard"]
CloneType = Literal["Type-1", "Type-2", "Type-3", "Type-4"]

_SEVERITY_WEIGHT: dict[Severity, int] = {"critical": 3, "warning": 2, "info": 1}
_EFFORT_WEIGHT: dict[Effort, int] = {"easy": 1, "moderate": 2, "hard": 3}


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _first_location(items: Sequence[GroupItemLike]) -> str:
    ordered = sorted(
        items,
        key=lambda item: (
            _as_str(item.get("filepath")),
            _as_int(item.get("start_line")),
            _as_int(item.get("end_line")),
            _as_str(item.get("qualname")),
        ),
    )
    if not ordered:
        return "(unknown)"
    item = ordered[0]
    filepath = _as_str(item.get("filepath"), "(unknown)")
    line = _as_int(item.get("start_line"), 0)
    return f"{filepath}:{line}"


def _priority(severity: Severity, effort: Effort) -> float:
    return float(_SEVERITY_WEIGHT[severity]) / float(_EFFORT_WEIGHT[effort])


def classify_clone_type(
    *,
    items: Sequence[GroupItemLike],
    kind: Literal["function", "block", "segment"],
) -> CloneType:
    if kind in {"block", "segment"}:
        return "Type-4"

    raw_hashes = sorted(
        {
            _as_str(item.get("raw_hash"))
            for item in items
            if _as_str(item.get("raw_hash"))
        }
    )
    fingerprints = sorted(
        {
            _as_str(item.get("fingerprint"))
            for item in items
            if _as_str(item.get("fingerprint"))
        }
    )
    if raw_hashes and len(raw_hashes) == 1:
        return "Type-1"
    if len(fingerprints) == 1:
        return "Type-2"
    if fingerprints:
        return "Type-3"
    return "Type-4"


def _clone_suggestions(
    *,
    func_groups: Mapping[str, Sequence[GroupItemLike]],
    block_groups: Mapping[str, Sequence[GroupItemLike]],
    segment_groups: Mapping[str, Sequence[GroupItemLike]],
) -> list[Suggestion]:
    suggestions: list[Suggestion] = []

    def _append_clone_suggestion(
        *,
        items: Sequence[GroupItemLike],
        severity: Severity,
        title: str,
        steps: tuple[str, ...],
        effort: Effort,
    ) -> None:
        suggestions.append(
            Suggestion(
                severity=severity,
                category="clone",
                title=title,
                location=_first_location(items),
                steps=steps,
                effort=effort,
                priority=_priority(severity, effort),
            )
        )

    for group_key, items in sorted(func_groups.items()):
        del group_key
        clone_type = classify_clone_type(items=items, kind="function")
        if len(items) >= 4:
            _append_clone_suggestion(
                items=items,
                severity="critical",
                title="High-fragment clone group (4+ occurrences)",
                steps=(
                    "Extract duplicated code into a shared function.",
                    "Replace all clone fragments with calls to the shared function.",
                ),
                effort="easy",
            )
        if clone_type == "Type-1":
            _append_clone_suggestion(
                items=items,
                severity="warning",
                title="Exact duplicate function clone (Type-1)",
                steps=(
                    "Extract exact duplicate into a shared function.",
                    "Keep one canonical implementation and remove duplicates.",
                ),
                effort="easy",
            )
        elif clone_type == "Type-2":
            _append_clone_suggestion(
                items=items,
                severity="warning",
                title="Parameterized clone candidate (Type-2)",
                steps=(
                    "Extract a single implementation with parameters.",
                    "Replace identifier-only variations with arguments.",
                ),
                effort="easy",
            )

    for groups in (block_groups, segment_groups):
        for _, items in sorted(groups.items()):
            if len(items) >= 4:
                _append_clone_suggestion(
                    items=items,
                    severity="critical",
                    title="Repeated structural block clone (4+ occurrences)",
                    steps=(
                        "Extract repeated logic into helper utilities.",
                        "Reduce copy-pasted assertion/setup blocks.",
                    ),
                    effort="easy",
                )

    return suggestions


def _complexity_suggestions(units: Sequence[GroupItemLike]) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for unit in sorted(
        units,
        key=lambda item: (
            _as_int(item.get("cyclomatic_complexity")),
            _as_int(item.get("nesting_depth")),
            _as_str(item.get("qualname")),
        ),
        reverse=True,
    ):
        cc = _as_int(unit.get("cyclomatic_complexity"), 1)
        if cc <= 20:
            continue
        severity: Severity = "critical" if cc > 40 else "warning"
        suggestions.append(
            Suggestion(
                severity=severity,
                category="complexity",
                title=(
                    "Extreme function complexity"
                    if cc > 40
                    else "High function complexity"
                ),
                location=_first_location([unit]),
                steps=(
                    "Split the function into smaller deterministic stages.",
                    "Extract helper functions for nested branches.",
                ),
                effort="moderate",
                priority=_priority(severity, "moderate"),
            )
        )
    return suggestions


def _coupling_and_cohesion_suggestions(
    class_metrics: Sequence[ClassMetrics],
) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for metric in sorted(
        class_metrics,
        key=lambda item: (item.filepath, item.start_line, item.end_line, item.qualname),
    ):
        location = f"{metric.filepath}:{metric.start_line}"
        if metric.cbo > 10:
            suggestions.append(
                Suggestion(
                    severity="warning",
                    category="coupling",
                    title="High coupling (CBO > 10)",
                    location=location,
                    steps=(
                        "Reduce external dependencies of this class.",
                        "Move unrelated responsibilities to collaborator classes.",
                    ),
                    effort="moderate",
                    priority=_priority("warning", "moderate"),
                )
            )
        if metric.lcom4 > 3:
            suggestions.append(
                Suggestion(
                    severity="warning",
                    category="cohesion",
                    title="Low cohesion (LCOM4 > 3)",
                    location=location,
                    steps=(
                        "Split class by responsibility boundaries.",
                        "Group methods by shared state and extract subcomponents.",
                    ),
                    effort="moderate",
                    priority=_priority("warning", "moderate"),
                )
            )
    return suggestions


def _dead_code_suggestions(project_metrics: ProjectMetrics) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for item in project_metrics.dead_code:
        if item.confidence != "high":
            continue
        suggestions.append(
            Suggestion(
                severity="warning",
                category="dead_code",
                title="Unused code with high confidence",
                location=f"{item.filepath}:{item.start_line}",
                steps=(
                    "Remove or deprecate the unused symbol.",
                    "If intentionally reserved, add explicit keep marker and test.",
                ),
                effort="easy",
                priority=_priority("warning", "easy"),
            )
        )
    return suggestions


def _dependency_suggestions(project_metrics: ProjectMetrics) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for cycle in project_metrics.dependency_cycles:
        location = " -> ".join(cycle)
        suggestions.append(
            Suggestion(
                severity="critical",
                category="dependency",
                title="Circular dependency detected",
                location=location,
                steps=(
                    "Break cycle by extracting shared abstractions.",
                    "Invert dependency direction with interfaces/protocols.",
                ),
                effort="hard",
                priority=_priority("critical", "hard"),
            )
        )
    return suggestions


def generate_suggestions(
    *,
    project_metrics: ProjectMetrics,
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    func_groups: Mapping[str, Sequence[GroupItemLike]],
    block_groups: Mapping[str, Sequence[GroupItemLike]],
    segment_groups: Mapping[str, Sequence[GroupItemLike]],
) -> tuple[Suggestion, ...]:
    suggestions = [
        *_clone_suggestions(
            func_groups=func_groups,
            block_groups=block_groups,
            segment_groups=segment_groups,
        ),
        *_complexity_suggestions(units),
        *_coupling_and_cohesion_suggestions(class_metrics),
        *_dead_code_suggestions(project_metrics),
        *_dependency_suggestions(project_metrics),
    ]
    return tuple(
        sorted(
            suggestions,
            key=lambda item: (
                -item.priority,
                item.severity,
                item.category,
                item.location,
                item.title,
            ),
        )
    )


__all__ = [
    "classify_clone_type",
    "generate_suggestions",
]
