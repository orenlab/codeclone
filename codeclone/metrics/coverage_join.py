# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

from ..models import CoverageJoinResult, GroupItemLike, UnitCoverageFact
from ..utils.coerce import as_int, as_str

__all__ = [
    "CoverageJoinParseError",
    "build_coverage_join",
]

_Risk = Literal["low", "medium", "high"]
_CoverageStatus = Literal["measured", "missing_from_report", "no_executable_lines"]

_MEASURED_STATUS: _CoverageStatus = "measured"
_MISSING_FROM_REPORT_STATUS: _CoverageStatus = "missing_from_report"
_NO_EXECUTABLE_LINES_STATUS: _CoverageStatus = "no_executable_lines"
_HOTSPOT_RISKS: frozenset[_Risk] = frozenset({"medium", "high"})


class CoverageJoinParseError(ValueError):
    """Raised when a Cobertura XML payload cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class _CoverageFileLines:
    executable_lines: frozenset[int]
    covered_lines: frozenset[int]


@dataclass(frozen=True, slots=True)
class _CoverageReport:
    files: dict[str, _CoverageFileLines]


def _permille(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round((1000.0 * float(numerator)) / float(denominator))


def _local_tag_name(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    _, _, local_name = tag.rpartition("}")
    return local_name or tag


def _normalized_relpath_text(value: str) -> str:
    return value.replace("\\", "/").strip()


def _resolved_path(candidate: Path) -> Path:
    try:
        return candidate.expanduser().resolve(strict=False)
    except OSError:
        return candidate.expanduser().absolute()


def _resolved_coverage_sources(
    *,
    root_element: ElementTree.Element,
    root_path: Path,
) -> tuple[Path, ...]:
    resolved: list[Path] = []
    seen: set[str] = set()
    for element in root_element.iter():
        text = _normalized_relpath_text(element.text or "")
        if _local_tag_name(element.tag) != "source" or not text:
            continue
        source_path = Path(text)
        if not source_path.is_absolute():
            source_path = root_path / source_path
        candidate = _resolved_path(source_path)
        key = str(candidate)
        if key not in seen:
            resolved.append(candidate)
            seen.add(key)
    fallback = _resolved_path(root_path)
    if str(fallback) not in seen:
        resolved.insert(0, fallback)
    return tuple(resolved)


def _resolve_report_filename(
    *,
    filename: str,
    root_path: Path,
    source_roots: Sequence[Path],
) -> str | None:
    normalized_filename = _normalized_relpath_text(filename)
    if not normalized_filename:
        return None
    raw_path = Path(normalized_filename)
    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(root_path / raw_path)
        candidates.extend(source_root / raw_path for source_root in source_roots)

    unique_candidates: list[Path] = []
    seen_candidates: set[str] = set()
    for candidate in candidates:
        resolved = _resolved_path(candidate)
        key = str(resolved)
        if key not in seen_candidates:
            unique_candidates.append(resolved)
            seen_candidates.add(key)

    under_root_existing: list[Path] = []
    under_root_fallback: list[Path] = []
    for candidate in unique_candidates:
        try:
            candidate.relative_to(root_path)
        except ValueError:
            continue
        if candidate.exists():
            under_root_existing.append(candidate)
        under_root_fallback.append(candidate)

    if under_root_existing:
        return str(sorted(under_root_existing)[0])
    if under_root_fallback:
        return str(under_root_fallback[0])
    return None


def _iter_cobertura_class_elements(
    root_element: ElementTree.Element,
) -> Sequence[ElementTree.Element]:
    return tuple(
        element
        for element in root_element.iter()
        if _local_tag_name(element.tag) == "class"
    )


def _iter_cobertura_line_hits(
    class_element: ElementTree.Element,
) -> Sequence[tuple[int, int]]:
    rows: list[tuple[int, int]] = []
    for line_element in class_element.iter():
        if _local_tag_name(line_element.tag) == "line":
            line_number = as_int(line_element.attrib.get("number"), -1)
            hits = as_int(line_element.attrib.get("hits"), -1)
            if line_number > 0 and hits >= 0:
                rows.append((line_number, hits))
    return tuple(rows)


def _parse_coverage_report(
    *,
    coverage_xml: Path,
    root_path: Path,
) -> _CoverageReport:
    try:
        tree = ElementTree.parse(coverage_xml)
    except (ElementTree.ParseError, OSError) as exc:
        raise CoverageJoinParseError(
            f"Invalid Cobertura XML at {coverage_xml}: {exc}"
        ) from exc

    root_element = tree.getroot()
    source_roots = _resolved_coverage_sources(
        root_element=root_element, root_path=root_path
    )
    file_lines: dict[str, dict[str, set[int]]] = defaultdict(
        lambda: {"executable": set(), "covered": set()}
    )

    for element in _iter_cobertura_class_elements(root_element):
        filename = element.attrib.get("filename", "")
        resolved_filename = _resolve_report_filename(
            filename=filename,
            root_path=root_path,
            source_roots=source_roots,
        )
        if resolved_filename is not None:
            target = file_lines[resolved_filename]
            for line_number, hits in _iter_cobertura_line_hits(element):
                target["executable"].add(line_number)
                if hits > 0:
                    target["covered"].add(line_number)

    return _CoverageReport(
        files={
            filepath: _CoverageFileLines(
                executable_lines=frozenset(sorted(lines["executable"])),
                covered_lines=frozenset(sorted(lines["covered"])),
            )
            for filepath, lines in sorted(file_lines.items())
        }
    )


def _unit_sort_key(item: GroupItemLike) -> tuple[str, int, int, str]:
    return (
        as_str(item.get("filepath")),
        as_int(item.get("start_line")),
        as_int(item.get("end_line")),
        as_str(item.get("qualname")),
    )


def _resolve_unit_path(filepath: str) -> str:
    return str(_resolved_path(Path(filepath)))


def _risk_level(value: object) -> _Risk:
    risk = as_str(value, "low")
    if risk == "medium":
        return "medium"
    if risk == "high":
        return "high"
    return "low"


def _unit_coverage_fact(
    *,
    unit: GroupItemLike,
    coverage_file: _CoverageFileLines | None,
) -> UnitCoverageFact:
    filepath = as_str(unit.get("filepath"))
    start_line = as_int(unit.get("start_line"))
    end_line = as_int(unit.get("end_line"))
    coverage_status: _CoverageStatus
    if coverage_file is None:
        executable_lines = 0
        covered_lines = 0
        coverage_permille = 0
        coverage_status = _MISSING_FROM_REPORT_STATUS
    else:
        executable_lines = sum(
            1
            for line_number in coverage_file.executable_lines
            if start_line <= line_number <= end_line
        )
        covered_lines = sum(
            1
            for line_number in coverage_file.covered_lines
            if start_line <= line_number <= end_line
        )
        coverage_permille = _permille(covered_lines, executable_lines)
        coverage_status = (
            _MEASURED_STATUS if executable_lines > 0 else _NO_EXECUTABLE_LINES_STATUS
        )
    return UnitCoverageFact(
        qualname=as_str(unit.get("qualname")),
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        cyclomatic_complexity=as_int(unit.get("cyclomatic_complexity"), 1),
        risk=_risk_level(unit.get("risk")),
        executable_lines=executable_lines,
        covered_lines=covered_lines,
        coverage_permille=coverage_permille,
        coverage_status=coverage_status,
    )


def _is_coverage_hotspot(
    *,
    fact: UnitCoverageFact,
    hotspot_threshold_percent: int,
) -> bool:
    if fact.risk not in _HOTSPOT_RISKS:
        return False
    if fact.coverage_status != _MEASURED_STATUS:
        return False
    return (fact.coverage_permille / 10.0) < float(hotspot_threshold_percent)


def _is_scope_gap_hotspot(*, fact: UnitCoverageFact) -> bool:
    return (
        fact.risk in _HOTSPOT_RISKS
        and fact.coverage_status == _MISSING_FROM_REPORT_STATUS
    )


def build_coverage_join(
    *,
    coverage_xml: Path,
    root_path: Path,
    units: Sequence[GroupItemLike],
    hotspot_threshold_percent: int,
) -> CoverageJoinResult:
    report = _parse_coverage_report(coverage_xml=coverage_xml, root_path=root_path)
    facts = tuple(
        _unit_coverage_fact(
            unit=unit,
            coverage_file=report.files.get(
                _resolve_unit_path(as_str(unit.get("filepath")))
            ),
        )
        for unit in sorted(units, key=_unit_sort_key)
    )
    measured_units = sum(
        1 for fact in facts if fact.coverage_status == _MEASURED_STATUS
    )
    overall_executable_lines = sum(fact.executable_lines for fact in facts)
    overall_covered_lines = sum(fact.covered_lines for fact in facts)
    return CoverageJoinResult(
        coverage_xml=str(_resolved_path(coverage_xml)),
        status="ok",
        hotspot_threshold_percent=hotspot_threshold_percent,
        files=len(report.files),
        measured_units=measured_units,
        overall_executable_lines=overall_executable_lines,
        overall_covered_lines=overall_covered_lines,
        coverage_hotspots=sum(
            1
            for fact in facts
            if _is_coverage_hotspot(
                fact=fact,
                hotspot_threshold_percent=hotspot_threshold_percent,
            )
        ),
        scope_gap_hotspots=sum(1 for fact in facts if _is_scope_gap_hotspot(fact=fact)),
        units=facts,
    )
