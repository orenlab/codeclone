# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

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
from ..findings.structural.detectors import normalize_structural_findings
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
from ..utils.coerce import as_int, as_str
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
from .messages import suggestions as sugg_msgs

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

_as_int = as_int
_as_str = as_str


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
    return sugg_msgs.CLONE_FACT_KIND_BY_KIND[kind]


def _clone_summary(
    *,
    kind: Literal["function", "block", "segment"],
    clone_type: CloneType,
    facts: Mapping[str, str],
) -> str:
    if kind == CLONE_KIND_FUNCTION:
        match clone_type:
            case "Type-1":
                return sugg_msgs.CLONE_SUMMARY_FUNCTION_TYPE1
            case "Type-2":
                return sugg_msgs.CLONE_SUMMARY_FUNCTION_TYPE2
            case "Type-3":
                return sugg_msgs.CLONE_SUMMARY_FUNCTION_TYPE3
            case _:
                return sugg_msgs.CLONE_SUMMARY_FUNCTION_TYPE4
    if kind == CLONE_KIND_BLOCK:
        hint = str(facts.get("hint", "")).strip()
        pattern = str(facts.get("pattern", "")).strip()
        if hint == BLOCK_HINT_ASSERT_ONLY:
            return sugg_msgs.CLONE_SUMMARY_BLOCK_ASSERT_ONLY
        if pattern == BLOCK_PATTERN_REPEATED_STMT_HASH:
            return sugg_msgs.CLONE_SUMMARY_BLOCK_REPEATED_STMT
        return sugg_msgs.CLONE_SUMMARY_BLOCK_DEFAULT
    return sugg_msgs.CLONE_SUMMARY_SEGMENT


def _clone_steps(
    *,
    kind: Literal["function", "block", "segment"],
    clone_type: CloneType,
    facts: Mapping[str, str],
) -> tuple[str, ...]:
    hint = str(facts.get("hint", "")).strip()
    if kind == CLONE_KIND_FUNCTION and clone_type == "Type-1":
        return (sugg_msgs.CLONE_STEP_TYPE1_1, sugg_msgs.CLONE_STEP_TYPE1_2)
    if kind == CLONE_KIND_FUNCTION and clone_type == "Type-2":
        return (sugg_msgs.CLONE_STEP_TYPE2_1, sugg_msgs.CLONE_STEP_TYPE2_2)
    if kind == CLONE_KIND_BLOCK and hint == BLOCK_HINT_ASSERT_ONLY:
        return (
            sugg_msgs.CLONE_STEP_BLOCK_ASSERT_1,
            sugg_msgs.CLONE_STEP_BLOCK_ASSERT_2,
        )
    if kind == CLONE_KIND_BLOCK:
        return (sugg_msgs.CLONE_STEP_BLOCK_1, sugg_msgs.CLONE_STEP_BLOCK_2)
    if kind == CLONE_KIND_SEGMENT:
        return (sugg_msgs.CLONE_STEP_SEGMENT_1, sugg_msgs.CLONE_STEP_SEGMENT_2)
    return (sugg_msgs.CLONE_STEP_DEFAULT_1, sugg_msgs.CLONE_STEP_DEFAULT_2)


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
                title=sugg_msgs.SUGGESTION_TITLE_REDUCE_COMPLEXITY,
                steps=(
                    sugg_msgs.COMPLEXITY_STEP_1,
                    sugg_msgs.COMPLEXITY_STEP_2,
                ),
                effort=EFFORT_MODERATE,
                fact_kind=sugg_msgs.FACT_KIND_COMPLEXITY_HOTSPOT,
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
                    title=sugg_msgs.SUGGESTION_TITLE_REDUCE_COUPLING,
                    steps=(
                        sugg_msgs.COUPLING_STEP_1,
                        sugg_msgs.COUPLING_STEP_2,
                    ),
                    effort=EFFORT_MODERATE,
                    fact_kind=sugg_msgs.FACT_KIND_COUPLING_HOTSPOT,
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
                    title=sugg_msgs.SUGGESTION_TITLE_SPLIT_COHESION,
                    steps=(
                        sugg_msgs.COHESION_STEP_1,
                        sugg_msgs.COHESION_STEP_2,
                    ),
                    effort=EFFORT_MODERATE,
                    fact_kind=sugg_msgs.FACT_KIND_LOW_COHESION,
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
                title=sugg_msgs.SUGGESTION_TITLE_DEAD_CODE,
                steps=(
                    sugg_msgs.DEAD_CODE_STEP_1,
                    sugg_msgs.DEAD_CODE_STEP_2,
                ),
                effort=EFFORT_EASY,
                fact_kind=sugg_msgs.FACT_KIND_DEAD_CODE,
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
                title=sugg_msgs.SUGGESTION_TITLE_BREAK_CYCLE,
                location=location,
                steps=(
                    sugg_msgs.DEPENDENCY_STEP_1,
                    sugg_msgs.DEPENDENCY_STEP_2,
                ),
                effort=EFFORT_HARD,
                priority=_priority(SEVERITY_CRITICAL, EFFORT_HARD),
                finding_family=FAMILY_METRICS,
                finding_kind="cycle",
                subject_key=location,
                fact_kind=sugg_msgs.FACT_KIND_DEPENDENCY_CYCLE,
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
                sugg_msgs.STRUCTURAL_TITLE_GUARD_EXIT_DIVERGENCE,
                sugg_msgs.STRUCTURAL_SUMMARY_GUARD_EXIT_DIVERGENCE,
            )
        case "clone_cohort_drift":
            return (
                sugg_msgs.STRUCTURAL_TITLE_COHORT_DRIFT,
                sugg_msgs.STRUCTURAL_SUMMARY_COHORT_DRIFT,
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
            return (
                sugg_msgs.STRUCTURAL_TITLE_REPEATED_BRANCH,
                sugg_msgs.STRUCTURAL_SUMMARY_RAISE_BRANCH,
            )
        case (False, "return", _):
            return (
                sugg_msgs.STRUCTURAL_TITLE_REPEATED_BRANCH,
                sugg_msgs.STRUCTURAL_SUMMARY_RETURN_BRANCH,
            )
        case (False, _, "1"):
            return (
                sugg_msgs.STRUCTURAL_TITLE_REPEATED_BRANCH,
                sugg_msgs.STRUCTURAL_SUMMARY_LOOP_BRANCH,
            )
        case _:
            if stmt_seq:
                return sugg_msgs.STRUCTURAL_TITLE_REPEATED_BRANCH, (
                    f"same repeated branch shape ({stmt_seq})"
                )
            return (
                sugg_msgs.STRUCTURAL_TITLE_REPEATED_BRANCH,
                sugg_msgs.STRUCTURAL_SUMMARY_BRANCH_DEFAULT,
            )


def structural_action_steps(group: StructuralFindingGroup) -> tuple[str, ...]:
    match group.finding_kind:
        case "clone_guard_exit_divergence":
            return (
                sugg_msgs.STRUCTURAL_STEP_GUARD_EXIT_1,
                sugg_msgs.STRUCTURAL_STEP_GUARD_EXIT_2,
            )
        case "clone_cohort_drift":
            return (
                sugg_msgs.STRUCTURAL_STEP_COHORT_DRIFT_1,
                sugg_msgs.STRUCTURAL_STEP_COHORT_DRIFT_2,
            )
        case _:
            pass

    terminal = str(group.signature.get("terminal", "")).strip()
    stmt_seq = str(group.signature.get("stmt_seq", "")).strip()
    stmt_names = tuple(part.strip() for part in stmt_seq.split(",") if part.strip())
    if "Continue" in stmt_names:
        return (
            sugg_msgs.STRUCTURAL_STEP_CONTINUE_1,
            sugg_msgs.STRUCTURAL_STEP_CONTINUE_2,
        )
    match terminal:
        case "raise":
            return (
                sugg_msgs.STRUCTURAL_STEP_RAISE_1,
                sugg_msgs.STRUCTURAL_STEP_RAISE_2,
            )
        case "return":
            return (
                sugg_msgs.STRUCTURAL_STEP_RETURN_1,
                sugg_msgs.STRUCTURAL_STEP_RETURN_2,
            )
        case _:
            return (
                sugg_msgs.STRUCTURAL_STEP_DEFAULT_1,
                sugg_msgs.STRUCTURAL_STEP_DEFAULT_2,
            )


def structural_suggestion_severity(
    group: StructuralFindingGroup,
    *,
    occurrence_count: int,
    spread_functions: int,
) -> Severity:
    severity: Severity = (
        SEVERITY_WARNING
        if occurrence_count >= 4 or spread_functions > 1
        else SEVERITY_INFO
    )
    if group.finding_kind in {
        "clone_guard_exit_divergence",
        "clone_cohort_drift",
    }:
        severity = SEVERITY_WARNING
    return severity


def structural_has_separate_suggestion(
    group: StructuralFindingGroup,
    *,
    occurrence_count: int,
    spread_functions: int,
) -> bool:
    return (
        structural_suggestion_severity(
            group,
            occurrence_count=occurrence_count,
            spread_functions=spread_functions,
        )
        != SEVERITY_INFO
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
        severity = structural_suggestion_severity(
            group,
            occurrence_count=count,
            spread_functions=spread_functions,
        )
        if not structural_has_separate_suggestion(
            group,
            occurrence_count=count,
            spread_functions=spread_functions,
        ):
            continue
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
                steps=structural_action_steps(group),
                effort=EFFORT_MODERATE,
                priority=_priority(severity, EFFORT_MODERATE),
                finding_family=FAMILY_STRUCTURAL,
                finding_kind=group.finding_kind,
                subject_key=group.finding_key,
                fact_kind=sugg_msgs.FACT_KIND_STRUCTURAL,
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
