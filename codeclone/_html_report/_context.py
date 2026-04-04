# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""ReportContext — immutable shared state for all section renderers."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .._coerce import as_mapping as _as_mapping
from ..contracts import REPORT_SCHEMA_VERSION
from ..report.overview import build_report_overview, materialize_report_overview

if TYPE_CHECKING:
    from .._html_snippets import _FileCache
    from ..models import (
        GroupItemLike,
        GroupMapLike,
        MetricsDiff,
        StructuralFindingGroup,
        Suggestion,
    )


@dataclass(frozen=True, slots=True)
class ReportContext:
    """Immutable bag of pre-extracted data passed to every section renderer."""

    # -- metadata --
    meta: Mapping[str, object]
    baseline_meta: Mapping[str, object]
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

    # -- clone groups (pre-sorted) --
    func_sorted: tuple[tuple[str, Sequence[GroupItemLike]], ...]
    block_sorted: tuple[tuple[str, Sequence[GroupItemLike]], ...]
    segment_sorted: tuple[tuple[str, Sequence[GroupItemLike]], ...]
    block_group_facts: dict[str, dict[str, str]]
    new_func_keys: frozenset[str]
    new_block_keys: frozenset[str]

    # -- metrics sub-maps --
    metrics_map: Mapping[str, object]
    complexity_map: Mapping[str, object]
    coupling_map: Mapping[str, object]
    cohesion_map: Mapping[str, object]
    dependencies_map: Mapping[str, object]
    dead_code_map: Mapping[str, object]
    overloaded_modules_map: Mapping[str, object]
    health_map: Mapping[str, object]

    # -- suggestions + structural --
    suggestions: tuple[Suggestion, ...]
    structural_findings: tuple[StructuralFindingGroup, ...]

    # -- derived --
    overview_data: Mapping[str, object]
    report_document: Mapping[str, object]
    inventory_map: Mapping[str, object]
    derived_map: Mapping[str, object]
    integrity_map: Mapping[str, object]

    # -- baseline diff --
    metrics_diff: MetricsDiff | None

    # -- rendering config --
    file_cache: _FileCache
    context_lines: int
    max_snippet_lines: int

    # -- convenience --
    @property
    def has_any_clones(self) -> bool:
        return bool(self.func_sorted or self.block_sorted or self.segment_sorted)

    @property
    def metrics_available(self) -> bool:
        return bool(self.metrics_map)

    @property
    def clone_groups_total(self) -> int:
        return len(self.func_sorted) + len(self.block_sorted) + len(self.segment_sorted)

    @property
    def clone_instances_total(self) -> int:
        return (
            sum(len(items) for _, items in self.func_sorted)
            + sum(len(items) for _, items in self.block_sorted)
            + sum(len(items) for _, items in self.segment_sorted)
        )

    def relative_path(self, abspath: str) -> str:
        """Strip scan_root prefix to get a concise project-relative path."""
        if not self.scan_root or not abspath:
            return abspath
        text = abspath.replace("\\", "/")
        root = self.scan_root.replace("\\", "/").rstrip("/") + "/"
        if text.startswith(root):
            return text[len(root) :]
        return abspath

    def bare_qualname(self, qualname: str, filepath: str) -> str:
        """Strip file-derived module prefix from qualname."""
        if not qualname:
            return qualname
        if ":" in qualname:
            return qualname.rsplit(":", maxsplit=1)[-1]
        if "." not in qualname:
            return qualname
        rel = self.relative_path(filepath)
        for suffix in ("/__init__.py", ".py"):
            if rel.endswith(suffix):
                rel = rel[: -len(suffix)]
                break
        prefix = rel.replace("/", ".") + "."
        if qualname.startswith(prefix):
            bare = qualname[len(prefix) :]
            if bare:
                return bare
        return qualname


def _group_sort_key(items: Collection[object]) -> tuple[int]:
    return (-len(items),)


def _meta_pick(*values: object) -> object | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def build_context(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    block_group_facts: dict[str, dict[str, str]],
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    report_meta: Mapping[str, object] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
    report_document: Mapping[str, object] | None = None,
    metrics_diff: MetricsDiff | None = None,
    file_cache: _FileCache,
    context_lines: int = 3,
    max_snippet_lines: int = 220,
) -> ReportContext:
    """Build a ReportContext from raw build_html_report parameters."""
    from .._html_escape import _escape_html

    meta = dict(report_meta or {})
    baseline_meta = _as_mapping(meta.get("baseline"))
    cache_meta = _as_mapping(meta.get("cache"))
    metrics_baseline_meta = _as_mapping(meta.get("metrics_baseline"))
    runtime_meta = _as_mapping(meta.get("runtime"))
    report_document_map = _as_mapping(report_document)
    inventory_map = _as_mapping(report_document_map.get("inventory"))
    derived_map = _as_mapping(report_document_map.get("derived"))
    integrity_map = _as_mapping(report_document_map.get("integrity"))

    report_schema_version = str(
        meta.get("report_schema_version") or REPORT_SCHEMA_VERSION
    )
    report_generated_at = str(
        _meta_pick(
            meta.get("report_generated_at_utc"),
            runtime_meta.get("report_generated_at_utc"),
        )
        or ""
    ).strip()
    brand_meta = (
        f"Generated at {report_generated_at}"
        if report_generated_at
        else f"Report schema {report_schema_version}"
    )
    scan_root_raw = str(
        _meta_pick(meta.get("scan_root"), runtime_meta.get("scan_root_absolute")) or ""
    ).strip()
    project_name_raw = str(meta.get("project_name", "")).strip()
    brand_project_html = (
        f' <span class="brand-project">for '
        f'<code class="brand-project-name">{_escape_html(project_name_raw)}</code>'
        f"</span>"
        if project_name_raw
        else ""
    )

    baseline_loaded = bool(meta.get("baseline_loaded"))
    baseline_status = str(meta.get("baseline_status", "")).strip().lower()
    if baseline_loaded and baseline_status == "ok":
        baseline_split_note = (
            "Split is based on baseline: known duplicates are already "
            "recorded in baseline, new duplicates are absent from baseline."
        )
    else:
        baseline_split_note = (
            "Baseline is not loaded or not trusted: "
            "all duplicates are treated as new versus an empty baseline."
        )

    func_sorted = tuple(
        sorted(func_groups.items(), key=lambda kv: (*_group_sort_key(kv[1]), kv[0]))
    )
    block_sorted = tuple(
        sorted(block_groups.items(), key=lambda kv: (*_group_sort_key(kv[1]), kv[0]))
    )
    segment_sorted = tuple(
        sorted(segment_groups.items(), key=lambda kv: (*_group_sort_key(kv[1]), kv[0]))
    )

    metrics_map = _as_mapping(metrics)
    complexity_map = _as_mapping(metrics_map.get("complexity"))
    coupling_map = _as_mapping(metrics_map.get("coupling"))
    cohesion_map = _as_mapping(metrics_map.get("cohesion"))
    dependencies_map = _as_mapping(metrics_map.get("dependencies"))
    dead_code_map = _as_mapping(metrics_map.get("dead_code"))
    overloaded_modules_map = _as_mapping(metrics_map.get("overloaded_modules"))
    if not overloaded_modules_map:
        overloaded_modules_map = _as_mapping(metrics_map.get("god_modules"))
    health_map = _as_mapping(metrics_map.get("health"))

    suggestions_tuple = tuple(suggestions or ())

    overview_data = _as_mapping(derived_map.get("overview"))
    if not overview_data:
        overview_data = build_report_overview(
            suggestions=list(suggestions_tuple),
            metrics=metrics_map,
        )
    else:
        overview_data = materialize_report_overview(
            overview=overview_data,
            hotlists=_as_mapping(derived_map.get("hotlists")),
            findings=_as_mapping(report_document_map.get("findings")),
        )

    return ReportContext(
        meta=meta,
        baseline_meta=baseline_meta,
        cache_meta=cache_meta,
        metrics_baseline_meta=metrics_baseline_meta,
        runtime_meta=runtime_meta,
        scan_root=scan_root_raw,
        project_name=project_name_raw,
        report_schema_version=report_schema_version,
        report_generated_at=report_generated_at,
        brand_meta=brand_meta,
        brand_project_html=brand_project_html,
        baseline_loaded=baseline_loaded,
        baseline_status=baseline_status,
        baseline_split_note=baseline_split_note,
        func_sorted=func_sorted,
        block_sorted=block_sorted,
        segment_sorted=segment_sorted,
        block_group_facts=block_group_facts,
        new_func_keys=frozenset(new_function_group_keys or ()),
        new_block_keys=frozenset(new_block_group_keys or ()),
        metrics_map=metrics_map,
        complexity_map=complexity_map,
        coupling_map=coupling_map,
        cohesion_map=cohesion_map,
        dependencies_map=dependencies_map,
        dead_code_map=dead_code_map,
        overloaded_modules_map=overloaded_modules_map,
        health_map=health_map,
        suggestions=suggestions_tuple,
        structural_findings=tuple(structural_findings or ()),
        overview_data=overview_data,
        report_document=report_document_map,
        inventory_map=inventory_map,
        derived_map=derived_map,
        integrity_map=integrity_map,
        metrics_diff=metrics_diff,
        file_cache=file_cache,
        context_lines=context_lines,
        max_snippet_lines=max_snippet_lines,
    )
