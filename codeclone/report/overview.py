# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ..domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_COVERAGE,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    FAMILY_CLONE,
    FAMILY_CLONES,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_METRICS,
    FAMILY_STRUCTURAL,
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT,
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
)
from ..domain.source_scope import (
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from ..domain.source_scope import SOURCE_KIND_ORDER as _SOURCE_KIND_ORDER
from ..report.explain_contract import (
    BLOCK_HINT_ASSERT_ONLY,
    BLOCK_PATTERN_REPEATED_STMT_HASH,
)
from ..utils.coerce import as_int as _as_int
from ..utils.coerce import as_mapping as _as_mapping
from ..utils.coerce import as_sequence as _as_sequence
from .derived import (
    classify_source_kind,
    format_spread_location_label,
    source_scope_from_locations,
)

if TYPE_CHECKING:
    from ..models import Suggestion

__all__ = [
    "build_directory_hotspots",
    "build_report_overview",
    "materialize_report_overview",
    "serialize_suggestion_card",
]


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


def _flatten_findings(findings: Mapping[str, object]) -> list[Mapping[str, object]]:
    groups = _as_mapping(findings.get("groups"))
    clone_groups = _as_mapping(groups.get(FAMILY_CLONES))
    return [
        *map(_as_mapping, _as_sequence(clone_groups.get("functions"))),
        *map(_as_mapping, _as_sequence(clone_groups.get("blocks"))),
        *map(_as_mapping, _as_sequence(clone_groups.get("segments"))),
        *map(
            _as_mapping,
            _as_sequence(_as_mapping(groups.get(FAMILY_STRUCTURAL)).get("groups")),
        ),
        *map(
            _as_mapping,
            _as_sequence(_as_mapping(groups.get(FAMILY_DEAD_CODE)).get("groups")),
        ),
        *map(
            _as_mapping,
            _as_sequence(_as_mapping(groups.get(FAMILY_DESIGN)).get("groups")),
        ),
    ]


_DIRECTORY_HOTSPOT_BUCKETS: tuple[str, ...] = (
    "all",
    "clones",
    "structural",
    CATEGORY_COMPLEXITY,
    CATEGORY_COHESION,
    CATEGORY_COUPLING,
    CATEGORY_DEAD_CODE,
    CATEGORY_DEPENDENCY,
)
_DIRECTORY_KIND_BREAKDOWN_KEYS: tuple[str, ...] = (
    "clones",
    "structural",
    CATEGORY_DEAD_CODE,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_COHESION,
    CATEGORY_COVERAGE,
    CATEGORY_DEPENDENCY,
)


@dataclass(slots=True)
class _DirectoryContribution:
    affected_items: int = 0
    files: set[str] = field(default_factory=set)
    locations: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class _DirectoryBucketRow:
    path: str
    finding_ids: set[str] = field(default_factory=set)
    affected_items: int = 0
    files: set[str] = field(default_factory=set)
    locations: list[dict[str, object]] = field(default_factory=list)
    kind_breakdown_ids: dict[str, set[str]] = field(
        default_factory=lambda: {key: set() for key in _DIRECTORY_KIND_BREAKDOWN_KEYS}
    )


def _directory_bucket_keys(group: Mapping[str, object]) -> tuple[str, ...]:
    family = str(group.get("family", "")).strip()
    category = str(group.get("category", "")).strip()
    if family == FAMILY_CLONE:
        return ("all", "clones")
    if family == FAMILY_STRUCTURAL:
        return ("all", "structural")
    if family == FAMILY_DEAD_CODE:
        return ("all", CATEGORY_DEAD_CODE)
    if family == FAMILY_DESIGN and category in {
        CATEGORY_COMPLEXITY,
        CATEGORY_COUPLING,
        CATEGORY_COHESION,
        CATEGORY_DEPENDENCY,
    }:
        return ("all", category)
    return ("all",)


def _directory_kind_breakdown_key(group: Mapping[str, object]) -> str | None:
    family = str(group.get("family", "")).strip()
    category = str(group.get("category", "")).strip()
    if family == FAMILY_CLONE:
        return "clones"
    if family == FAMILY_STRUCTURAL:
        return "structural"
    if family == FAMILY_DEAD_CODE:
        return CATEGORY_DEAD_CODE
    if family == FAMILY_DESIGN and category in {
        CATEGORY_COMPLEXITY,
        CATEGORY_COUPLING,
        CATEGORY_COHESION,
        CATEGORY_COVERAGE,
        CATEGORY_DEPENDENCY,
    }:
        return category
    return None


def _directory_relative_path(item: Mapping[str, object]) -> str | None:
    relative_path = str(item.get("relative_path", "")).replace("\\", "/").strip()
    if not relative_path:
        module = str(item.get("module", "")).strip()
        if module:
            relative_path = module.replace(".", "/") + ".py"
    return relative_path or None


def _directory_path_label(relative_path: str) -> str:
    parent = PurePosixPath(relative_path).parent.as_posix()
    return parent if parent not in {"", "/"} else "."


def _directory_scope_root_label(
    relative_path: str,
    *,
    source_kind: str,
) -> str | None:
    parts = tuple(
        part for part in PurePosixPath(relative_path).parts if part not in {"", "."}
    )
    if not parts:
        return None
    tests_idx = next(
        (index for index, part in enumerate(parts) if part == SOURCE_KIND_TESTS),
        None,
    )
    if tests_idx is None:
        return None
    if (
        source_kind == SOURCE_KIND_FIXTURES
        and tests_idx + 1 < len(parts)
        and parts[tests_idx + 1] == SOURCE_KIND_FIXTURES
    ):
        return "/".join(parts[: tests_idx + 2])
    if source_kind == SOURCE_KIND_TESTS:
        return "/".join(parts[: tests_idx + 1])
    return None


def _overview_directory_label(
    relative_path: str,
    *,
    source_kind: str,
) -> str:
    scope_root = _directory_scope_root_label(
        relative_path,
        source_kind=source_kind,
    )
    if scope_root:
        return scope_root
    return _directory_path_label(relative_path)


def _directory_contributions(
    group: Mapping[str, object],
) -> dict[str, _DirectoryContribution]:
    contributions: dict[str, _DirectoryContribution] = {}
    for item in map(_as_mapping, _as_sequence(group.get("items"))):
        relative_path = _directory_relative_path(item)
        if relative_path is None:
            continue
        source_kind = str(item.get("source_kind", "")).strip() or classify_source_kind(
            relative_path
        )
        directory = _overview_directory_label(relative_path, source_kind=source_kind)
        entry = contributions.setdefault(directory, _DirectoryContribution())
        entry.affected_items += 1
        entry.files.add(relative_path)
        entry.locations.append({"source_kind": source_kind})
    return contributions


def _directory_group_data(
    group: Mapping[str, object],
) -> tuple[str, dict[str, _DirectoryContribution]] | None:
    group_id = str(group.get("id", "")).strip()
    if not group_id:
        return None
    contributions = _directory_contributions(group)
    if not contributions:
        return None
    return group_id, contributions


def build_directory_hotspots(
    *,
    findings: Mapping[str, object],
    limit: int = 5,
) -> dict[str, object]:
    normalized_limit = max(1, _as_int(limit, 5))
    bucket_rows: dict[str, dict[str, _DirectoryBucketRow]] = {
        bucket: {} for bucket in _DIRECTORY_HOTSPOT_BUCKETS
    }
    bucket_totals: Counter[str] = Counter()

    for group in _flatten_findings(findings):
        group_data = _directory_group_data(group)
        if group_data is None:
            continue
        group_id, contributions = group_data
        bucket_keys = _directory_bucket_keys(group)
        kind_key = _directory_kind_breakdown_key(group)
        for bucket in bucket_keys:
            rows = bucket_rows[bucket]
            for directory, contribution in contributions.items():
                row = rows.setdefault(
                    directory,
                    _DirectoryBucketRow(path=directory),
                )
                row.finding_ids.add(group_id)
                row.affected_items += contribution.affected_items
                row.files.update(contribution.files)
                row.locations.extend(contribution.locations)
                if bucket == "all" and kind_key is not None:
                    row.kind_breakdown_ids[kind_key].add(group_id)
                bucket_totals[bucket] += contribution.affected_items

    def _row_sort_key(row: _DirectoryBucketRow) -> tuple[int, int, int, str]:
        return (
            -len(row.finding_ids),
            -row.affected_items,
            -len(row.files),
            row.path,
        )

    hotspots: dict[str, object] = {}
    for bucket in _DIRECTORY_HOTSPOT_BUCKETS:
        bucket_items = sorted(bucket_rows[bucket].values(), key=_row_sort_key)
        total_directories = len(bucket_items)
        total_affected_items = bucket_totals[bucket]
        items: list[dict[str, object]] = []
        for row in bucket_items[:normalized_limit]:
            finding_groups = len(row.finding_ids)
            affected_items = row.affected_items
            files = len(row.files)
            item = {
                "path": row.path,
                "finding_groups": finding_groups,
                "affected_items": affected_items,
                "files": files,
                "share_pct": round(
                    (affected_items / total_affected_items) * 100.0,
                    1,
                )
                if total_affected_items > 0
                else 0.0,
                "source_scope": source_scope_from_locations(row.locations),
            }
            if bucket == "all":
                item["kind_breakdown"] = {
                    key: len(row.kind_breakdown_ids[key])
                    for key in _DIRECTORY_KIND_BREAKDOWN_KEYS
                }
            items.append(item)
        hotspots[bucket] = {
            "total_directories": total_directories,
            "returned": len(items),
            "has_more": total_directories > len(items),
            "items": items,
        }
    return hotspots


def _clone_fact_kind(kind: str) -> str:
    return {
        CLONE_KIND_FUNCTION: "Function clone group",
        CLONE_KIND_BLOCK: "Block clone group",
        CLONE_KIND_SEGMENT: "Segment clone group",
    }.get(kind, "Clone group")


def _clone_summary_from_group(group: Mapping[str, object]) -> str:
    kind = str(group.get("category", "")).strip()
    clone_type = str(group.get("clone_type", "")).strip()
    facts = _as_mapping(group.get("facts"))
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


def _structural_summary_from_group(group: Mapping[str, object]) -> tuple[str, str]:
    category = str(group.get("category", "")).strip()
    if category == STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE:
        return (
            "Clone guard/exit divergence",
            "clone cohort members differ in entry guards or early-exit behavior",
        )
    if category == STRUCTURAL_KIND_CLONE_COHORT_DRIFT:
        return (
            "Clone cohort drift",
            "clone cohort members drift from majority terminal/guard/try profile",
        )

    signature = _as_mapping(group.get("signature"))
    debug = _as_mapping(signature.get("debug"))
    terminal = str(
        _as_mapping(signature.get("stable")).get(
            "terminal_kind",
            debug.get("terminal", ""),
        )
    ).strip()
    stmt_seq = str(debug.get("stmt_seq", "")).strip()
    raises = str(debug.get("raises", "")).strip()
    has_loop = str(debug.get("has_loop", "")).strip()
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


def _single_item_location(item: Mapping[str, object]) -> str:
    module = str(item.get("module", "")).strip()
    if module:
        return module
    relative_path = str(item.get("relative_path", "")).strip()
    if not relative_path:
        return "(unknown)"
    start_line = _as_int(item.get("start_line"))
    end_line = _as_int(item.get("end_line"))
    if start_line <= 0:
        return relative_path
    line = f"{start_line}-{end_line}" if end_line > start_line else str(start_line)
    return f"{relative_path}:{line}"


def _group_location_label(group: Mapping[str, object]) -> str:
    items = tuple(_as_mapping(item) for item in _as_sequence(group.get("items")))
    category = str(group.get("category", "")).strip()
    if category == CATEGORY_DEPENDENCY:
        modules = [str(item.get("module", "")).strip() for item in items]
        joined = " -> ".join(module for module in modules if module)
        if joined:
            return joined
    count = _as_int(group.get("count"))
    if count <= 1 and items:
        return _single_item_location(items[0])
    spread = _as_mapping(group.get("spread"))
    files = _as_int(spread.get("files"))
    functions = _as_int(spread.get("functions"))
    return format_spread_location_label(
        count,
        files=files,
        functions=functions,
    )


def serialize_finding_group_card(group: Mapping[str, object]) -> dict[str, object]:
    family = str(group.get("family", "")).strip()
    category = str(group.get("category", "")).strip()
    facts = _as_mapping(group.get("facts"))
    source_scope = _as_mapping(group.get("source_scope"))

    title = "Finding"
    summary = ""
    clone_type = str(group.get("clone_type", "")).strip()
    if family == "clone":
        title = f"{_clone_fact_kind(category)} ({clone_type or 'Type-4'})"
        summary = _clone_summary_from_group(group)
    elif family == FAMILY_STRUCTURAL:
        title, summary = _structural_summary_from_group(group)
    elif family == FAMILY_DEAD_CODE:
        title = "Remove or explicitly keep unused code"
        confidence = str(group.get("confidence", "medium")).strip() or "medium"
        summary = f"{category or 'symbol'} with {confidence} confidence"
    elif family == FAMILY_DESIGN:
        if category == CATEGORY_COMPLEXITY:
            title = "Reduce high-complexity function"
            summary = (
                "cyclomatic_complexity="
                f"{_as_int(facts.get('cyclomatic_complexity'))}, "
                f"nesting_depth={_as_int(facts.get('nesting_depth'))}"
            )
        elif category == CATEGORY_COUPLING:
            title = "Split high-coupling class"
            summary = f"cbo={_as_int(facts.get('cbo'))}"
        elif category == CATEGORY_COHESION:
            title = "Split low-cohesion class"
            summary = f"lcom4={_as_int(facts.get('lcom4'))}"
        elif category == CATEGORY_DEPENDENCY:
            title = "Break circular dependency"
            cycle_length = _as_int(
                facts.get("cycle_length"),
                _as_int(group.get("count")),
            )
            summary = f"{cycle_length} modules participate in this cycle"
        elif category == CATEGORY_COVERAGE:
            kind = str(group.get("kind", "")).strip()
            coverage_status = str(facts.get("coverage_status", "")).strip()
            threshold = _as_int(facts.get("hotspot_threshold_percent"))
            if kind == "coverage_scope_gap" or coverage_status == "missing_from_report":
                title = "Include risky function in coverage input"
                summary = "coverage.xml did not include this function's file"
            else:
                title = "Increase coverage for risky function"
                summary = (
                    f"coverage={_as_int(facts.get('coverage_permille')) / 10.0:.1f}%, "
                    f"threshold={threshold}%"
                )

    return {
        "title": title,
        "family": family,
        "category": category,
        "summary": summary,
        "severity": str(group.get("severity", "info")),
        "priority": group.get("priority"),
        "confidence": str(group.get("confidence", "medium")),
        "source_kind": str(source_scope.get("dominant_kind", SOURCE_KIND_OTHER)).strip()
        or SOURCE_KIND_OTHER,
        "location": _group_location_label(group),
        "clone_type": clone_type,
        "count": _as_int(group.get("count")),
        "spread": {
            "files": _as_int(_as_mapping(group.get("spread")).get("files")),
            "functions": _as_int(_as_mapping(group.get("spread")).get("functions")),
        },
    }


def materialize_report_overview(
    *,
    overview: Mapping[str, object],
    hotlists: Mapping[str, object],
    findings: Mapping[str, object],
) -> dict[str, object]:
    materialized = dict(overview)
    if "source_breakdown" not in materialized:
        materialized["source_breakdown"] = dict(
            _as_mapping(overview.get("source_scope_breakdown"))
        )

    finding_index = {
        str(group.get("id")): group for group in _flatten_findings(findings)
    }
    for overview_key, hotlist_key in (
        ("most_actionable", "most_actionable_ids"),
        ("highest_spread", "highest_spread_ids"),
        ("production_hotspots", "production_hotspot_ids"),
        ("test_fixture_hotspots", "test_fixture_hotspot_ids"),
    ):
        if _as_sequence(materialized.get(overview_key)):
            continue
        materialized[overview_key] = [
            serialize_finding_group_card(group)
            for finding_id in _as_sequence(hotlists.get(hotlist_key))
            if (group := _as_mapping(finding_index.get(str(finding_id))))
        ]
    return materialized


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
    ordered_kinds = tuple(
        sorted(_SOURCE_KIND_ORDER, key=lambda kind: _SOURCE_KIND_ORDER[kind])
    )
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


def _metric_summary_count(
    metrics: Mapping[str, object],
    metric_name: str,
    summary_key: str,
    *,
    fallback_key: str | None = None,
) -> int:
    metric_map = metrics.get(metric_name)
    if not isinstance(metric_map, Mapping):
        return 0
    summary = metric_map.get("summary")
    if not isinstance(summary, Mapping):
        return 0
    return int(summary.get(summary_key, summary.get(fallback_key, 0)))


def _top_risks(
    suggestions: Sequence[Suggestion],
    *,
    metrics: Mapping[str, object],
) -> list[str]:
    risks: list[str] = []
    high_conf = _metric_summary_count(
        metrics,
        "dead_code",
        "high_confidence",
        fallback_key="critical",
    )
    if high_conf > 0:
        noun = "item" if high_conf == 1 else "items"
        risks.append(f"{high_conf} dead code {noun}")

    low = _metric_summary_count(metrics, "cohesion", "low_cohesion")
    if low > 0:
        noun = "class" if low == 1 else "classes"
        risks.append(f"{low} low cohesion {noun}")
    production_structural = sum(
        1
        for suggestion in suggestions
        if suggestion.finding_family == FAMILY_STRUCTURAL
        and suggestion.source_kind == SOURCE_KIND_PRODUCTION
    )
    if production_structural > 0:
        noun = "finding" if production_structural == 1 else "findings"
        risks.append(f"{production_structural} structural {noun} in production code")
    test_clone_groups = sum(
        1
        for suggestion in suggestions
        if suggestion.finding_family == FAMILY_CLONES
        and suggestion.source_kind in {SOURCE_KIND_TESTS, SOURCE_KIND_FIXTURES}
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
        if suggestion.finding_family == FAMILY_METRICS
        and suggestion.category != CATEGORY_DEAD_CODE
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
                if suggestion.source_kind == SOURCE_KIND_PRODUCTION
            ),
            key=_card_key,
        )
    )[:5]
    test_fixture_hotspots = tuple(
        sorted(
            (
                suggestion
                for suggestion in suggestions
                if suggestion.source_kind in {SOURCE_KIND_TESTS, SOURCE_KIND_FIXTURES}
            ),
            key=_card_key,
        )
    )[:5]
    return {
        "families": {
            "clone_groups": sum(
                1
                for suggestion in suggestions
                if suggestion.finding_family == FAMILY_CLONES
            ),
            "structural_findings": sum(
                1
                for suggestion in suggestions
                if suggestion.finding_family == FAMILY_STRUCTURAL
            ),
            "dead_code": sum(
                1
                for suggestion in suggestions
                if suggestion.category == CATEGORY_DEAD_CODE
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
