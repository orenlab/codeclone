# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical report-document projection shared by HTML section renderers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from ...contracts import REPORT_SCHEMA_VERSION
from ...utils.coerce import as_float as _as_float
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ...utils.mapping_paths import section, sections

if TYPE_CHECKING:
    from .widgets.snippets import _FileCache


@dataclass(frozen=True, slots=True)
class ReportContext:
    """Immutable presentation DTO extracted from one canonical report document."""

    meta: Mapping[str, object]
    baseline_meta: Mapping[str, object]
    comparison: Mapping[str, object]
    cache_meta: Mapping[str, object]
    metrics_baseline_meta: Mapping[str, object]
    runtime_meta: Mapping[str, object]
    scan_root: str
    project_name: str
    report_schema_version: str
    report_generated_at: str
    brand_meta: str
    brand_project_html: str
    baseline_loaded: bool
    baseline_status: str
    baseline_split_note: str
    func_sorted: tuple[tuple[str, Sequence[Mapping[str, object]]], ...]
    block_sorted: tuple[tuple[str, Sequence[Mapping[str, object]]], ...]
    segment_sorted: tuple[tuple[str, Sequence[Mapping[str, object]]], ...]
    block_group_facts: dict[str, dict[str, object]]
    new_func_keys: frozenset[str]
    new_block_keys: frozenset[str]
    func_novelty: Mapping[str, str]
    block_novelty: Mapping[str, str]
    segment_novelty: Mapping[str, str]
    clone_summary: Mapping[str, object]
    metrics_map: Mapping[str, object]
    complexity_map: Mapping[str, object]
    coupling_map: Mapping[str, object]
    cohesion_map: Mapping[str, object]
    dependencies_map: Mapping[str, object]
    dead_code_map: Mapping[str, object]
    overloaded_modules_map: Mapping[str, object]
    security_surfaces_map: Mapping[str, object]
    health_map: Mapping[str, object]
    suggestions: tuple[SimpleNamespace, ...]
    structural_findings: tuple[SimpleNamespace, ...]
    overview_data: Mapping[str, object]
    report_document: Mapping[str, object]
    inventory_map: Mapping[str, object]
    derived_map: Mapping[str, object]
    integrity_map: Mapping[str, object]
    file_cache: _FileCache
    context_lines: int
    max_snippet_lines: int

    @property
    def has_any_clones(self) -> bool:
        return any(
            _as_int(self.clone_summary.get(kind))
            for kind in ("functions", "blocks", "segments")
        )

    @property
    def metrics_available(self) -> bool:
        return bool(self.metrics_map)

    @property
    def clone_groups_total(self) -> int:
        return (
            _as_int(self.clone_summary.get("functions"))
            + _as_int(self.clone_summary.get("blocks"))
            + _as_int(self.clone_summary.get("segments"))
        )

    @property
    def clone_instances_total(self) -> int:
        return _as_int(self.clone_summary.get("instances"))

    def relative_path(self, path: str) -> str:
        return path


def _meta_pick(*values: object) -> object | None:
    for value in values:
        if value is not None and (not isinstance(value, str) or value.strip()):
            return value
    return None


def _absolute_presentation_path(relative_path: str, *, scan_root: str) -> str:
    if not relative_path or not scan_root:
        return relative_path
    return str(Path(scan_root, relative_path))


def _clone_projection(
    raw_groups: object,
    *,
    scan_root: str,
) -> tuple[
    tuple[tuple[str, Sequence[Mapping[str, object]]], ...],
    dict[str, str],
    dict[str, dict[str, object]],
]:
    rows: list[tuple[str, Sequence[Mapping[str, object]]]] = []
    novelty: dict[str, str] = {}
    facts: dict[str, dict[str, object]] = {}
    for raw_group in _as_sequence(raw_groups):
        group = _as_mapping(raw_group)
        group_id = str(
            _as_mapping(group.get("facts")).get(
                "group_key",
                group.get("id", ""),
            )
        )
        items = tuple(
            {
                **dict(item),
                "filepath": _absolute_presentation_path(
                    str(item.get("relative_path", "")),
                    scan_root=scan_root,
                ),
            }
            for raw_item in _as_sequence(group.get("items"))
            for item in (_as_mapping(raw_item),)
        )
        rows.append((group_id, items))
        novelty[group_id] = str(group.get("novelty", "unavailable"))
        group_facts = {
            str(key): (str(value).lower() if isinstance(value, bool) else value)
            for key, value in _as_mapping(group.get("facts")).items()
        }
        group_facts.update(_as_mapping(group.get("display_facts")))
        facts[group_id] = group_facts
    return tuple(rows), novelty, facts


def _suggestion_projection(raw: object, *, scan_root: str) -> SimpleNamespace:
    row = _as_mapping(raw)
    action = _as_mapping(row.get("action"))
    locations = tuple(
        SimpleNamespace(
            **dict(location),
            filepath=_absolute_presentation_path(
                str(location.get("relative_path", "")),
                scan_root=scan_root,
            ),
        )
        for raw_location in _as_sequence(row.get("representative_locations"))
        for location in (_as_mapping(raw_location),)
    )
    return SimpleNamespace(
        severity=str(row.get("severity", "info")),
        category=str(row.get("category", "")),
        title=str(row.get("title", "")),
        location=str(row.get("location", "")),
        steps=tuple(str(step) for step in _as_sequence(action.get("steps"))),
        effort=str(action.get("effort", "moderate")),
        priority=_as_float(row.get("priority")),
        finding_family=str(row.get("finding_family", "")),
        finding_kind=str(row.get("finding_kind", "")),
        subject_key=str(row.get("subject_key", "")),
        fact_kind=str(row.get("fact_kind", "")),
        fact_summary=str(row.get("summary", "")),
        fact_count=_as_int(row.get("fact_count")),
        spread_files=_as_int(row.get("spread_files")),
        spread_functions=_as_int(row.get("spread_functions")),
        clone_type=str(row.get("clone_type", "")),
        confidence=str(row.get("confidence", "medium")),
        source_kind=str(row.get("source_kind", "other")),
        source_breakdown=tuple(
            tuple(pair)
            for pair in _as_sequence(row.get("source_breakdown"))
            if isinstance(pair, Sequence) and len(pair) == 2
        ),
        representative_locations=locations,
        location_label=str(row.get("location_label", "")),
    )


def _structural_projection(raw: object, *, scan_root: str) -> SimpleNamespace:
    row = _as_mapping(raw)
    finding_kind = str(row.get("category", row.get("kind", "")))
    finding_id = str(row.get("id", ""))
    finding_prefix = f"structural:{finding_kind}:"
    finding_key = (
        finding_id.removeprefix(finding_prefix)
        if finding_id.startswith(finding_prefix)
        else finding_id
    )
    items = tuple(
        SimpleNamespace(
            finding_kind=finding_kind,
            finding_key=finding_key,
            file_path=_absolute_presentation_path(
                str(item.get("relative_path", "")),
                scan_root=scan_root,
            ),
            qualname=str(item.get("qualname", "")),
            start=_as_int(item.get("start_line")),
            end=_as_int(item.get("end_line")),
            signature=dict(_as_mapping(row.get("signature"))),
        )
        for raw_item in _as_sequence(row.get("items"))
        for item in (_as_mapping(raw_item),)
    )
    return SimpleNamespace(
        finding_kind=finding_kind,
        finding_key=finding_key,
        signature=dict(_as_mapping(row.get("signature"))),
        items=items,
    )


def _metric_family_projection(
    raw: object,
    *,
    scan_root: str,
    item_alias: str | None = None,
) -> Mapping[str, object]:
    family = dict(_as_mapping(raw))
    if not family:
        return {}
    raw_items = _as_sequence(family.get("items"))
    summary = dict(_as_mapping(family.get("summary")))
    if summary.get("source") is None:
        summary["source"] = ""
    family["summary"] = summary
    for key, value in summary.items():
        family.setdefault(key, value)
    items = [
        {
            **dict(item),
            "filepath": _absolute_presentation_path(
                str(item.get("relative_path", "")),
                scan_root=scan_root,
            ),
        }
        for raw_item in raw_items
        for item in (_as_mapping(raw_item),)
    ]
    family["items"] = items
    if item_alias is not None:
        family[item_alias] = items
    return family


def build_context(
    *,
    report_document: Mapping[str, object],
    file_cache: _FileCache,
    context_lines: int = 3,
    max_snippet_lines: int = 220,
) -> ReportContext:
    """Project one canonical report document into presentation-only DTOs."""

    from .primitives.escape import _escape_html

    document = _as_mapping(report_document)
    meta = _as_mapping(document.get("meta"))
    runtime_meta = _as_mapping(meta.get("runtime"))
    comparison = _as_mapping(document.get("baseline"))
    scan_root = str(runtime_meta.get("scan_root_absolute") or "").strip()
    project_name = str(meta.get("project_name", "")).strip()
    generated_at = str(runtime_meta.get("report_generated_at_utc", "")).strip()
    schema_version = str(document.get("report_schema_version", REPORT_SCHEMA_VERSION))
    lane_rows = tuple(
        _as_mapping(row) for row in _as_sequence(comparison.get("sorted_lane_trust"))
    )
    trusted_lanes = sum(
        1 for row in lane_rows if str(row.get("status", "")) == "trusted"
    )
    unavailable_lanes = len(lane_rows) - trusted_lanes
    baseline_split_note = (
        f"Per-lane baseline trust: {trusted_lanes} trusted, "
        f"{unavailable_lanes} unavailable."
    )

    findings_summary, groups, clones = sections(
        document,
        "findings.summary",
        "findings.groups",
        "findings.groups.clones",
    )
    func_sorted, func_novelty, _func_facts = _clone_projection(
        clones.get("functions"),
        scan_root=scan_root,
    )
    block_sorted, block_novelty, block_facts = _clone_projection(
        clones.get("blocks"),
        scan_root=scan_root,
    )
    segment_sorted, segment_novelty, _segment_facts = _clone_projection(
        clones.get("segments"),
        scan_root=scan_root,
    )

    metric_families = section(document, "metrics.families")
    computed_metric_families = frozenset(
        str(name)
        for name in _as_sequence(meta.get("computed_metric_families"))
        if str(name).strip()
    )
    presentation_families = {
        str(name): payload
        for name, payload in metric_families.items()
        if not computed_metric_families or str(name) in computed_metric_families
    }
    metric_families_view = {
        str(name): _metric_family_projection(payload, scan_root=scan_root)
        for name, payload in presentation_families.items()
    }
    inventory, inventory_files = sections(document, "inventory", "inventory.files")
    health_summary = section(presentation_families, "health.summary")
    presentation_meta = dict(meta)
    presentation_meta.update(
        {
            "files_skipped_source_io": _as_int(
                inventory_files.get("source_io_skipped")
            ),
            "health_score": health_summary.get("score"),
            "health_grade": health_summary.get("grade"),
            # Carried beside the two fields it qualifies. Without it the
            # provenance table cannot tell "n/a because metrics were skipped"
            # apart from "n/a because no source file was read".
            "health_population": health_summary.get("population"),
        }
    )
    derived = _as_mapping(document.get("derived"))
    structural_groups = _as_sequence(
        _as_mapping(groups.get("structural")).get("groups")
    )
    baseline_state = str(comparison.get("state", "missing"))
    return ReportContext(
        meta=presentation_meta,
        baseline_meta=_as_mapping(meta.get("baseline")),
        comparison=comparison,
        cache_meta=_as_mapping(meta.get("cache")),
        metrics_baseline_meta=_as_mapping(meta.get("metrics_baseline")),
        runtime_meta=runtime_meta,
        scan_root=scan_root,
        project_name=project_name,
        report_schema_version=schema_version,
        report_generated_at=generated_at,
        brand_meta=(
            f"Generated at {generated_at}"
            if generated_at
            else f"Report schema {schema_version}"
        ),
        brand_project_html=(
            f' <span class="brand-project">for '
            f'<code class="brand-project-name">{_escape_html(project_name)}</code>'
            f"</span>"
            if project_name
            else ""
        ),
        baseline_loaded=baseline_state == "trusted",
        baseline_status=baseline_state,
        baseline_split_note=baseline_split_note,
        func_sorted=func_sorted,
        block_sorted=block_sorted,
        segment_sorted=segment_sorted,
        block_group_facts=block_facts,
        new_func_keys=frozenset(
            key for key, state in func_novelty.items() if state == "new"
        ),
        new_block_keys=frozenset(
            key for key, state in block_novelty.items() if state == "new"
        ),
        func_novelty=func_novelty,
        block_novelty=block_novelty,
        segment_novelty=segment_novelty,
        clone_summary=_as_mapping(findings_summary.get("clones")),
        metrics_map=metric_families_view,
        complexity_map=_metric_family_projection(
            presentation_families.get("complexity"),
            scan_root=scan_root,
            item_alias="functions",
        ),
        coupling_map=_metric_family_projection(
            presentation_families.get("coupling"),
            scan_root=scan_root,
            item_alias="classes",
        ),
        cohesion_map=_metric_family_projection(
            presentation_families.get("cohesion"),
            scan_root=scan_root,
            item_alias="classes",
        ),
        dependencies_map=_metric_family_projection(
            presentation_families.get("dependencies"),
            scan_root=scan_root,
            item_alias="edge_list",
        ),
        dead_code_map=_metric_family_projection(
            presentation_families.get("dead_code"),
            scan_root=scan_root,
        ),
        overloaded_modules_map=_metric_family_projection(
            presentation_families.get("overloaded_modules"),
            scan_root=scan_root,
        ),
        security_surfaces_map=_metric_family_projection(
            presentation_families.get("security_surfaces"),
            scan_root=scan_root,
        ),
        health_map=_metric_family_projection(
            presentation_families.get("health"),
            scan_root=scan_root,
        ),
        suggestions=tuple(
            _suggestion_projection(row, scan_root=scan_root)
            for row in _as_sequence(derived.get("suggestions"))
        ),
        structural_findings=tuple(
            _structural_projection(row, scan_root=scan_root)
            for row in structural_groups
        ),
        overview_data=_as_mapping(derived.get("overview")),
        report_document=document,
        inventory_map=inventory,
        derived_map=derived,
        integrity_map=_as_mapping(document.get("integrity")),
        file_cache=file_cache,
        context_lines=context_lines,
        max_snippet_lines=max_snippet_lines,
    )


__all__ = ["ReportContext", "_meta_pick", "build_context"]
