# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .. import _coerce
from ..domain.findings import (
    CATEGORY_CLONE,
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CATEGORY_STRUCTURAL,
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    FAMILY_CLONES,
    FAMILY_METRICS,
    FAMILY_STRUCTURAL,
)
from ..domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    EFFORT_EASY,
    EFFORT_HARD,
    EFFORT_MODERATE,
    EFFORT_WEIGHT,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_RANK,
    SEVERITY_WARNING,
)
from ..models import (
    ClassMetrics,
    GroupItemLike,
    ProjectMetrics,
    ReportLocation,
    SourceKind,
    StructuralFindingGroup,
    Suggestion,
)
from ..report.explain_contract import (
    BLOCK_HINT_ASSERT_ONLY,
    BLOCK_PATTERN_REPEATED_STMT_HASH,
)
from ..structural_findings import normalize_structural_findings
from .derived import (
    combine_source_kinds,
    format_group_location_label,
    format_report_location_label,
    group_spread,
    relative_report_path,
    report_location_from_group_item,
    report_location_from_structural_occurrence,
    representative_locations,
    source_kind_breakdown,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

Severity = Literal["critical", "warning", "info"]
Effort = Literal["easy", "moderate", "hard"]
CloneType = Literal["Type-1", "Type-2", "Type-3", "Type-4"]
SuggestionCategory = Literal[
    "clone",
    "structural",
    "complexity",
    "coupling",
    "cohesion",
    "dead_code",
    "dependency",
]

_as_int = _coerce.as_int
_as_str = _coerce.as_str


def _priority(severity: Severity, effort: Effort) -> float:
    return float(SEVERITY_RANK[severity]) / float(EFFORT_WEIGHT[effort])


def classify_clone_type(
    *,
    items: Sequence[GroupItemLike],
    kind: Literal["function", "block", "segment"],
) -> CloneType:
    if kind in {CLONE_KIND_BLOCK, CLONE_KIND_SEGMENT}:
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


def _source_context(
    locations: Sequence[ReportLocation],
    *,
    scan_root: str,
) -> tuple[SourceKind, tuple[tuple[SourceKind, int], ...]]:
    breakdown = source_kind_breakdown(
        (location.filepath for location in locations),
        scan_root=scan_root,
    )
    source_kind = combine_source_kinds(kind for kind, _count in breakdown)
    return source_kind, breakdown


def _clone_fact_kind(kind: Literal["function", "block", "segment"]) -> str:
    return {
        CLONE_KIND_FUNCTION: "Function clone group",
        CLONE_KIND_BLOCK: "Block clone group",
        CLONE_KIND_SEGMENT: "Segment clone group",
    }[kind]


def _clone_summary(
    *,
    kind: Literal["function", "block", "segment"],
    clone_type: CloneType,
    facts: Mapping[str, str],
) -> str:
    if kind == CLONE_KIND_FUNCTION:
        match clone_type:
            case "Type-1":
                return "same exact function body"
            case "Type-2":
                return "same parameterized function body"
            case "Type-3":
                return "same structural function body with small identifier changes"
            case _:
                return "same structural function body"
    if kind == CLONE_KIND_BLOCK:
        hint = str(facts.get("hint", "")).strip()
        pattern = str(facts.get("pattern", "")).strip()
        if hint == BLOCK_HINT_ASSERT_ONLY:
            return "same assertion template"
        if pattern == BLOCK_PATTERN_REPEATED_STMT_HASH:
            return "same repeated setup/assert pattern"
        return "same structural sequence with small value changes"
    return "same structural segment sequence"


def _clone_steps(
    *,
    kind: Literal["function", "block", "segment"],
    clone_type: CloneType,
    facts: Mapping[str, str],
) -> tuple[str, ...]:
    hint = str(facts.get("hint", "")).strip()
    if kind == CLONE_KIND_FUNCTION and clone_type == "Type-1":
        return (
            "Keep one canonical implementation and remove the exact duplicates.",
            "Route the remaining call sites to the shared implementation.",
        )
    if kind == CLONE_KIND_FUNCTION and clone_type == "Type-2":
        return (
            "Extract a shared implementation with explicit parameters.",
            "Replace identifier-only variations with arguments.",
        )
    if kind == CLONE_KIND_BLOCK and hint == BLOCK_HINT_ASSERT_ONLY:
        return (
            "Collapse the repeated assertion template into a helper or loop.",
            "Keep the asserted values as data instead of copy-pasted statements.",
        )
    if kind == CLONE_KIND_BLOCK:
        return (
            "Extract the repeated statement sequence into a helper.",
            "Keep setup data close to the call site and move shared logic out.",
        )
    if kind == CLONE_KIND_SEGMENT:
        return (
            "Review whether the repeated segment should become shared utility code.",
            "Keep this as a report hint only if the duplication is intentional.",
        )
    return (
        "Extract the repeated logic into a shared abstraction.",
        "Replace the duplicated bodies with calls to the shared code.",
    )


def _clone_suggestion(
    *,
    group_key: str,
    items: Sequence[GroupItemLike],
    kind: Literal["function", "block", "segment"],
    facts: Mapping[str, str],
    scan_root: str,
) -> Suggestion:
    locations = tuple(
        report_location_from_group_item(item, scan_root=scan_root) for item in items
    )
    representative = representative_locations(locations)
    spread_files, spread_functions = group_spread(locations)
    clone_type = classify_clone_type(items=items, kind=kind)
    source_kind, breakdown = _source_context(locations, scan_root=scan_root)
    count = len(items)
    severity: Severity
    if count >= 4:
        severity = SEVERITY_CRITICAL
    elif clone_type in {"Type-1", "Type-2"}:
        severity = SEVERITY_WARNING
    else:
        severity = SEVERITY_INFO
    effort: Effort = (
        EFFORT_EASY if clone_type in {"Type-1", "Type-2"} else EFFORT_MODERATE
    )
    summary = _clone_summary(kind=kind, clone_type=clone_type, facts=facts)
    location_label = format_group_location_label(
        representative,
        total_count=count,
        spread_files=spread_files,
        spread_functions=spread_functions,
    )
    return Suggestion(
        severity=severity,
        category=CATEGORY_CLONE,
        title=f"{_clone_fact_kind(kind)} ({clone_type})",
        location=location_label,
        steps=_clone_steps(kind=kind, clone_type=clone_type, facts=facts),
        effort=effort,
        priority=_priority(severity, effort),
        finding_family=FAMILY_CLONES,
        finding_kind=kind,
        subject_key=group_key,
        fact_kind=_clone_fact_kind(kind),
        fact_summary=summary,
        fact_count=count,
        spread_files=spread_files,
        spread_functions=spread_functions,
        clone_type=clone_type,
        confidence=CONFIDENCE_HIGH,
        source_kind=source_kind,
        source_breakdown=breakdown,
        representative_locations=representative,
        location_label=location_label,
    )


def _clone_suggestions(
    *,
    func_groups: Mapping[str, Sequence[GroupItemLike]],
    block_groups: Mapping[str, Sequence[GroupItemLike]],
    segment_groups: Mapping[str, Sequence[GroupItemLike]],
    block_group_facts: Mapping[str, Mapping[str, str]],
    scan_root: str,
) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for group_key, items in sorted(func_groups.items()):
        suggestions.append(
            _clone_suggestion(
                group_key=group_key,
                items=items,
                kind=CLONE_KIND_FUNCTION,
                facts={},
                scan_root=scan_root,
            )
        )
    for group_key, items in sorted(block_groups.items()):
        suggestions.append(
            _clone_suggestion(
                group_key=group_key,
                items=items,
                kind=CLONE_KIND_BLOCK,
                facts=block_group_facts.get(group_key, {}),
                scan_root=scan_root,
            )
        )
    for group_key, items in sorted(segment_groups.items()):
        suggestions.append(
            _clone_suggestion(
                group_key=group_key,
                items=items,
                kind=CLONE_KIND_SEGMENT,
                facts={},
                scan_root=scan_root,
            )
        )
    return suggestions


def _single_location_suggestion(
    *,
    severity: Severity,
    category: SuggestionCategory,
    title: str,
    steps: tuple[str, ...],
    effort: Effort,
    fact_kind: str,
    fact_summary: str,
    filepath: str,
    start_line: int,
    end_line: int,
    qualname: str,
    subject_key: str,
    finding_kind: str,
    confidence: Literal["high", "medium", "low"],
    scan_root: str,
) -> Suggestion:
    source_kind = report_location_from_group_item(
        {
            "filepath": filepath,
            "start_line": start_line,
            "end_line": end_line,
            "qualname": qualname,
        },
        scan_root=scan_root,
    ).source_kind
    location = ReportLocation(
        filepath=filepath,
        relative_path=relative_report_path(filepath, scan_root=scan_root),
        start_line=start_line,
        end_line=end_line,
        qualname=qualname,
        source_kind=source_kind,
    )
    location_label = format_report_location_label(location)
    return Suggestion(
        severity=severity,
        category=category,
        title=title,
        location=location_label,
        steps=steps,
        effort=effort,
        priority=_priority(severity, effort),
        finding_family=FAMILY_METRICS,
        finding_kind=finding_kind,
        subject_key=subject_key,
        fact_kind=fact_kind,
        fact_summary=fact_summary,
        fact_count=1,
        spread_files=1,
        spread_functions=1,
        confidence=confidence,
        source_kind=location.source_kind,
        source_breakdown=((location.source_kind, 1),),
        representative_locations=(location,),
        location_label=location_label,
    )


def _complexity_suggestions(
    units: Sequence[GroupItemLike],
    *,
    scan_root: str,
) -> list[Suggestion]:
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
        severity: Severity = SEVERITY_CRITICAL if cc > 40 else SEVERITY_WARNING
        nesting = _as_int(unit.get("nesting_depth"))
        qualname = _as_str(unit.get("qualname"))
        suggestions.append(
            _single_location_suggestion(
                severity=severity,
                category=CATEGORY_COMPLEXITY,
                title="Reduce function complexity",
                steps=(
                    "Split the function into smaller deterministic stages.",
                    "Extract helper functions for nested branches.",
                ),
                effort=EFFORT_MODERATE,
                fact_kind="Function complexity hotspot",
                fact_summary=f"cyclomatic_complexity={cc}, nesting_depth={nesting}",
                filepath=_as_str(unit.get("filepath")),
                start_line=_as_int(unit.get("start_line")),
                end_line=_as_int(unit.get("end_line")),
                qualname=qualname,
                subject_key=qualname,
                finding_kind="function_hotspot",
                confidence=CONFIDENCE_HIGH,
                scan_root=scan_root,
            )
        )
    return suggestions


def _coupling_and_cohesion_suggestions(
    class_metrics: Sequence[ClassMetrics],
    *,
    scan_root: str,
) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for metric in sorted(
        class_metrics,
        key=lambda item: (item.filepath, item.start_line, item.end_line, item.qualname),
    ):
        if metric.cbo > 10:
            suggestions.append(
                _single_location_suggestion(
                    severity=SEVERITY_WARNING,
                    category=CATEGORY_COUPLING,
                    title="Reduce class coupling",
                    steps=(
                        "Reduce external dependencies of this class.",
                        "Move unrelated responsibilities to collaborator classes.",
                    ),
                    effort=EFFORT_MODERATE,
                    fact_kind="Class coupling hotspot",
                    fact_summary=f"cbo={metric.cbo}",
                    filepath=metric.filepath,
                    start_line=metric.start_line,
                    end_line=metric.end_line,
                    qualname=metric.qualname,
                    subject_key=metric.qualname,
                    finding_kind="class_hotspot",
                    confidence=CONFIDENCE_HIGH,
                    scan_root=scan_root,
                )
            )
        if metric.lcom4 > 3:
            suggestions.append(
                _single_location_suggestion(
                    severity=SEVERITY_WARNING,
                    category=CATEGORY_COHESION,
                    title="Split low-cohesion class",
                    steps=(
                        "Split class by responsibility boundaries.",
                        "Group methods by shared state and extract subcomponents.",
                    ),
                    effort=EFFORT_MODERATE,
                    fact_kind="Low cohesion class",
                    fact_summary=f"lcom4={metric.lcom4}",
                    filepath=metric.filepath,
                    start_line=metric.start_line,
                    end_line=metric.end_line,
                    qualname=metric.qualname,
                    subject_key=metric.qualname,
                    finding_kind="class_hotspot",
                    confidence=CONFIDENCE_HIGH,
                    scan_root=scan_root,
                )
            )
    return suggestions


def _dead_code_suggestions(
    project_metrics: ProjectMetrics,
    *,
    scan_root: str,
) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for item in project_metrics.dead_code:
        if item.confidence != CONFIDENCE_HIGH:
            continue
        suggestions.append(
            _single_location_suggestion(
                severity=SEVERITY_WARNING,
                category=CATEGORY_DEAD_CODE,
                title="Remove or explicitly keep unused code",
                steps=(
                    "Remove or deprecate the unused symbol.",
                    "If intentionally reserved, add explicit keep marker and test.",
                ),
                effort=EFFORT_EASY,
                fact_kind="Dead code item",
                fact_summary=f"{item.kind} with {item.confidence} confidence",
                filepath=item.filepath,
                start_line=item.start_line,
                end_line=item.end_line,
                qualname=item.qualname,
                subject_key=item.qualname,
                finding_kind="unused_symbol",
                confidence=CONFIDENCE_HIGH,
                scan_root=scan_root,
            )
        )
    return suggestions


def _module_source_kind(modules: Sequence[str]) -> SourceKind:
    pseudo_paths = tuple(module.replace(".", "/") + ".py" for module in modules)
    return combine_source_kinds(
        source_kind for source_kind, _count in source_kind_breakdown(pseudo_paths)
    )


def _dependency_suggestions(project_metrics: ProjectMetrics) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for cycle in project_metrics.dependency_cycles:
        location = " -> ".join(cycle)
        source_kind = _module_source_kind(list(cycle))
        suggestions.append(
            Suggestion(
                severity=SEVERITY_CRITICAL,
                category=CATEGORY_DEPENDENCY,
                title="Break circular dependency",
                location=location,
                steps=(
                    "Break the cycle by extracting a shared abstraction.",
                    "Invert one dependency edge through an interface or protocol.",
                ),
                effort=EFFORT_HARD,
                priority=_priority(SEVERITY_CRITICAL, EFFORT_HARD),
                finding_family=FAMILY_METRICS,
                finding_kind="cycle",
                subject_key=location,
                fact_kind="Dependency cycle",
                fact_summary=f"{len(cycle)} modules participate in this cycle",
                fact_count=len(cycle),
                spread_files=len(cycle),
                spread_functions=0,
                confidence=CONFIDENCE_HIGH,
                source_kind=source_kind,
                source_breakdown=((source_kind, len(cycle)),),
                location_label=location,
            )
        )
    return suggestions


def _structural_summary(group: StructuralFindingGroup) -> tuple[str, str]:
    match group.finding_kind:
        case "clone_guard_exit_divergence":
            return (
                "Clone guard/exit divergence",
                "clone cohort members differ in entry guards or early-exit behavior",
            )
        case "clone_cohort_drift":
            return (
                "Clone cohort drift",
                "clone cohort members drift from majority terminal/guard/try profile",
            )
        case _:
            pass

    terminal = str(group.signature.get("terminal", "")).strip()
    stmt_seq = str(group.signature.get("stmt_seq", "")).strip()
    raises = str(group.signature.get("raises", "")).strip()
    has_loop = str(group.signature.get("has_loop", "")).strip()
    raise_like = terminal == "raise" or raises not in {"", "0"}
    match (raise_like, terminal, has_loop):
        case (True, _, _):
            return "Repeated branch family", "same repeated guard/validation branch"
        case (False, "return", _):
            return "Repeated branch family", "same repeated return branch"
        case (False, _, "1"):
            return "Repeated branch family", "same repeated loop branch"
        case _:
            if stmt_seq:
                return "Repeated branch family", (
                    f"same repeated branch shape ({stmt_seq})"
                )
            return "Repeated branch family", "same repeated branch shape"


def _structural_steps(group: StructuralFindingGroup) -> tuple[str, ...]:
    match group.finding_kind:
        case "clone_guard_exit_divergence":
            return (
                (
                    "Compare divergent clone members against the majority "
                    "guard/exit profile."
                ),
                "If divergence is accidental, align guard exits across the cohort.",
            )
        case "clone_cohort_drift":
            return (
                "Review whether cohort drift is intentional for this clone family.",
                (
                    "If not intentional, reconcile terminal/guard/try profiles "
                    "across members."
                ),
            )
        case _:
            pass

    terminal = str(group.signature.get("terminal", "")).strip()
    match terminal:
        case "raise":
            return (
                "Factor the repeated validation/guard path into a shared helper.",
                (
                    "Keep the branch-specific inputs at the call site and share "
                    "the exit policy."
                ),
            )
        case "return":
            return (
                "Consolidate the repeated return-path logic into a shared helper.",
                "Keep the branch predicate local and share the emitted behavior.",
            )
        case _:
            return (
                "Review whether the repeated branch family should become a helper.",
                (
                    "Keep this as a report-only hint if the local duplication is "
                    "intentional."
                ),
            )


def _structural_suggestions(
    structural_findings: Sequence[StructuralFindingGroup],
    *,
    scan_root: str,
) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for group in normalize_structural_findings(structural_findings):
        locations = tuple(
            report_location_from_structural_occurrence(item, scan_root=scan_root)
            for item in group.items
        )
        representative = representative_locations(locations)
        spread_files, spread_functions = group_spread(locations)
        source_kind, breakdown = _source_context(locations, scan_root=scan_root)
        count = len(locations)
        severity: Severity = (
            SEVERITY_WARNING if count >= 4 or spread_functions > 1 else SEVERITY_INFO
        )
        if group.finding_kind in {
            "clone_guard_exit_divergence",
            "clone_cohort_drift",
        }:
            severity = SEVERITY_WARNING
        title, summary = _structural_summary(group)
        location_label = format_group_location_label(
            representative,
            total_count=count,
            spread_files=spread_files,
            spread_functions=spread_functions,
        )
        suggestions.append(
            Suggestion(
                severity=severity,
                category=CATEGORY_STRUCTURAL,
                title=title,
                location=location_label,
                steps=_structural_steps(group),
                effort=EFFORT_MODERATE,
                priority=_priority(severity, EFFORT_MODERATE),
                finding_family=FAMILY_STRUCTURAL,
                finding_kind=group.finding_kind,
                subject_key=group.finding_key,
                fact_kind="Structural finding",
                fact_summary=summary,
                fact_count=count,
                spread_files=spread_files,
                spread_functions=spread_functions,
                confidence=(
                    CONFIDENCE_HIGH
                    if group.finding_kind
                    in {"clone_guard_exit_divergence", "clone_cohort_drift"}
                    else CONFIDENCE_MEDIUM
                ),
                source_kind=source_kind,
                source_breakdown=breakdown,
                representative_locations=representative,
                location_label=location_label,
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
    block_group_facts: Mapping[str, Mapping[str, str]] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
    scan_root: str = "",
) -> tuple[Suggestion, ...]:
    suggestions = [
        *_clone_suggestions(
            func_groups=func_groups,
            block_groups=block_groups,
            segment_groups=segment_groups,
            block_group_facts=block_group_facts or {},
            scan_root=scan_root,
        ),
        *_structural_suggestions(structural_findings or (), scan_root=scan_root),
        *_complexity_suggestions(units, scan_root=scan_root),
        *_coupling_and_cohesion_suggestions(class_metrics, scan_root=scan_root),
        *_dead_code_suggestions(project_metrics, scan_root=scan_root),
        *_dependency_suggestions(project_metrics),
    ]
    return tuple(
        sorted(
            suggestions,
            key=lambda item: (
                -item.priority,
                item.severity,
                item.category,
                item.source_kind,
                item.location_label or item.location,
                item.title,
                item.subject_key,
            ),
        )
    )


__all__ = [
    "classify_clone_type",
    "generate_suggestions",
]
