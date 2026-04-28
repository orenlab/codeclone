# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from ..domain.source_scope import (
    IMPACT_SCOPE_MIXED,
    IMPACT_SCOPE_NON_RUNTIME,
    IMPACT_SCOPE_RUNTIME,
    SOURCE_KIND_BREAKDOWN_KEYS,
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_MIXED,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from ..domain.source_scope import (
    SOURCE_KIND_ORDER as _SOURCE_KIND_ORDER,
)
from ..models import ReportLocation, SourceKind, StructuralFindingOccurrence
from ..paths import (
    classify_source_kind as _classify_source_kind,
)
from ..paths import (
    relative_repo_path as _relative_repo_path,
)
from ..utils.coerce import as_int as _as_int

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "SOURCE_KIND_ORDER",
    "classify_source_kind",
    "combine_source_kinds",
    "format_group_location_label",
    "format_report_location_label",
    "format_spread_location_label",
    "group_spread",
    "normalized_source_kind",
    "relative_report_path",
    "report_location_from_group_item",
    "report_location_from_structural_occurrence",
    "representative_locations",
    "source_kind_breakdown",
    "source_scope_from_counts",
    "source_scope_from_locations",
]

SOURCE_KIND_ORDER: dict[SourceKind, int] = {
    SOURCE_KIND_PRODUCTION: _SOURCE_KIND_ORDER[SOURCE_KIND_PRODUCTION],
    SOURCE_KIND_TESTS: _SOURCE_KIND_ORDER[SOURCE_KIND_TESTS],
    SOURCE_KIND_FIXTURES: _SOURCE_KIND_ORDER[SOURCE_KIND_FIXTURES],
    SOURCE_KIND_MIXED: _SOURCE_KIND_ORDER[SOURCE_KIND_MIXED],
    SOURCE_KIND_OTHER: _SOURCE_KIND_ORDER[SOURCE_KIND_OTHER],
}


def relative_report_path(filepath: str, *, scan_root: str = "") -> str:
    return _relative_repo_path(filepath, scan_root=scan_root)


def classify_source_kind(filepath: str, *, scan_root: str = "") -> SourceKind:
    normalized = _classify_source_kind(filepath, scan_root=scan_root)
    if normalized == SOURCE_KIND_PRODUCTION:
        return SOURCE_KIND_PRODUCTION
    if normalized == SOURCE_KIND_TESTS:
        return SOURCE_KIND_TESTS
    if normalized == SOURCE_KIND_FIXTURES:
        return SOURCE_KIND_FIXTURES
    return SOURCE_KIND_OTHER


def source_kind_breakdown(
    filepaths: Iterable[str],
    *,
    scan_root: str = "",
) -> tuple[tuple[SourceKind, int], ...]:
    counts: Counter[SourceKind] = Counter(
        classify_source_kind(filepath, scan_root=scan_root) for filepath in filepaths
    )
    return tuple(
        (kind, counts[kind])
        for kind in sorted(counts, key=lambda item: SOURCE_KIND_ORDER[item])
        if counts[kind] > 0
    )


def combine_source_kinds(
    kinds: Iterable[SourceKind] | Iterable[str],
) -> SourceKind:
    normalized = tuple(str(kind).strip().lower() for kind in kinds if str(kind).strip())
    if not normalized:
        return SOURCE_KIND_OTHER
    allowed: tuple[SourceKind, ...] = (
        SOURCE_KIND_PRODUCTION,
        SOURCE_KIND_TESTS,
        SOURCE_KIND_FIXTURES,
        SOURCE_KIND_MIXED,
        SOURCE_KIND_OTHER,
    )
    unique = tuple(kind for kind in allowed if kind in set(normalized))
    if len(unique) == 1:
        return unique[0]
    return SOURCE_KIND_MIXED


def normalized_source_kind(value: object) -> SourceKind:
    source_kind_text = str(value).strip().lower() or SOURCE_KIND_OTHER
    if source_kind_text == SOURCE_KIND_PRODUCTION:
        return SOURCE_KIND_PRODUCTION
    if source_kind_text == SOURCE_KIND_TESTS:
        return SOURCE_KIND_TESTS
    if source_kind_text == SOURCE_KIND_FIXTURES:
        return SOURCE_KIND_FIXTURES
    return SOURCE_KIND_OTHER


def source_scope_from_counts(
    counts: Mapping[SourceKind, int] | Mapping[str, int],
) -> dict[str, object]:
    normalized_counts = {str(key): int(value) for key, value in counts.items()}

    def _count(kind: str) -> int:
        value = normalized_counts.get(kind, 0)
        return int(value)

    breakdown = {kind: _count(kind) for kind in SOURCE_KIND_BREAKDOWN_KEYS}
    present = tuple(kind for kind in SOURCE_KIND_BREAKDOWN_KEYS if breakdown[kind] > 0)
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


def source_scope_from_locations(
    locations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    counts: Counter[SourceKind] = Counter()
    for location in locations:
        counts[normalized_source_kind(location.get("source_kind"))] += 1
    return source_scope_from_counts(counts)


def report_location_from_group_item(
    item: Mapping[str, object],
    *,
    scan_root: str = "",
) -> ReportLocation:
    filepath = str(item.get("filepath", ""))
    start_line = _as_int(item.get("start_line"))
    end_line = _as_int(item.get("end_line"))
    qualname = str(item.get("qualname", ""))
    return ReportLocation(
        filepath=filepath,
        relative_path=relative_report_path(filepath, scan_root=scan_root),
        start_line=start_line,
        end_line=end_line,
        qualname=qualname,
        source_kind=classify_source_kind(filepath, scan_root=scan_root),
    )


def report_location_from_structural_occurrence(
    item: StructuralFindingOccurrence,
    *,
    scan_root: str = "",
) -> ReportLocation:
    return ReportLocation(
        filepath=item.file_path,
        relative_path=relative_report_path(item.file_path, scan_root=scan_root),
        start_line=item.start,
        end_line=item.end,
        qualname=item.qualname,
        source_kind=classify_source_kind(item.file_path, scan_root=scan_root),
    )


def _location_key(location: ReportLocation) -> tuple[str, int, int, str]:
    return (
        location.relative_path or location.filepath,
        location.start_line,
        location.end_line,
        location.qualname,
    )


def representative_locations(
    locations: Sequence[ReportLocation],
    *,
    limit: int = 3,
) -> tuple[ReportLocation, ...]:
    unique: dict[tuple[str, int, int, str], ReportLocation] = {}
    for location in sorted(locations, key=_location_key):
        key = _location_key(location)
        if key not in unique:
            unique[key] = location
    return tuple(list(unique.values())[:limit])


def group_spread(locations: Sequence[ReportLocation]) -> tuple[int, int]:
    file_count = len(
        {location.relative_path or location.filepath for location in locations}
    )
    function_count = len(
        {location.qualname for location in locations if location.qualname}
    )
    return file_count, function_count


def format_report_location_label(location: ReportLocation) -> str:
    line = (
        f"{location.start_line}-{location.end_line}"
        if location.end_line > location.start_line
        else str(location.start_line)
    )
    return f"{location.relative_path}:{line}"


def format_spread_location_label(
    total_count: int,
    *,
    files: int,
    functions: int,
) -> str:
    count_word = "occurrence" if total_count == 1 else "occurrences"
    file_word = "file" if files == 1 else "files"
    function_word = "function" if functions == 1 else "functions"
    return (
        f"{total_count} {count_word} across "
        f"{files} {file_word} / {functions} {function_word}"
    )


def format_group_location_label(
    locations: Sequence[ReportLocation],
    *,
    total_count: int,
    spread_files: int | None = None,
    spread_functions: int | None = None,
) -> str:
    if total_count <= 0 or not locations:
        return "(unknown)"
    if total_count == 1:
        return format_report_location_label(locations[0])
    files = spread_files if spread_files is not None else group_spread(locations)[0]
    functions = (
        spread_functions if spread_functions is not None else group_spread(locations)[1]
    )
    return format_spread_location_label(
        total_count,
        files=files,
        functions=functions,
    )
