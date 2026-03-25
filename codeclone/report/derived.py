# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .. import _coerce
from ..domain.source_scope import (
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
    "relative_report_path",
    "report_location_from_group_item",
    "report_location_from_structural_occurrence",
    "representative_locations",
    "source_kind_breakdown",
]

SOURCE_KIND_ORDER: dict[SourceKind, int] = {
    SOURCE_KIND_PRODUCTION: _SOURCE_KIND_ORDER[SOURCE_KIND_PRODUCTION],
    SOURCE_KIND_TESTS: _SOURCE_KIND_ORDER[SOURCE_KIND_TESTS],
    SOURCE_KIND_FIXTURES: _SOURCE_KIND_ORDER[SOURCE_KIND_FIXTURES],
    SOURCE_KIND_MIXED: _SOURCE_KIND_ORDER[SOURCE_KIND_MIXED],
    SOURCE_KIND_OTHER: _SOURCE_KIND_ORDER[SOURCE_KIND_OTHER],
}

_as_int = _coerce.as_int


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def relative_report_path(filepath: str, *, scan_root: str = "") -> str:
    normalized_path = _normalize_path(filepath)
    normalized_root = _normalize_path(scan_root).rstrip("/")
    if not normalized_path:
        return normalized_path
    if not normalized_root:
        return normalized_path
    prefix = f"{normalized_root}/"
    if normalized_path.startswith(prefix):
        return normalized_path[len(prefix) :]
    if normalized_path == normalized_root:
        return normalized_path.rsplit("/", maxsplit=1)[-1]
    return normalized_path


def classify_source_kind(filepath: str, *, scan_root: str = "") -> SourceKind:
    rel = relative_report_path(filepath, scan_root=scan_root)
    parts = [part for part in rel.lower().split("/") if part and part != "."]
    if not parts:
        return SOURCE_KIND_OTHER
    for idx, part in enumerate(parts):
        if part != SOURCE_KIND_TESTS:
            continue
        if idx + 1 < len(parts) and parts[idx + 1] == SOURCE_KIND_FIXTURES:
            return SOURCE_KIND_FIXTURES
        return SOURCE_KIND_TESTS
    return SOURCE_KIND_PRODUCTION


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
