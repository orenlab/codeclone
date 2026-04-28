# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ._canonicalize import _normalized_optional_string_list
from .entries import CacheEntry, ClassMetricsDict


def _encode_source_stats(entry: CacheEntry, wire: dict[str, object]) -> None:
    source_stats = entry.get("source_stats")
    if source_stats is not None:
        wire["ss"] = [
            source_stats["lines"],
            source_stats["functions"],
            source_stats["methods"],
            source_stats["classes"],
        ]


def _encode_units(entry: CacheEntry, wire: dict[str, object]) -> None:
    units = sorted(
        entry["units"],
        key=lambda unit: (
            unit["qualname"],
            unit["start_line"],
            unit["end_line"],
            unit["fingerprint"],
        ),
    )
    if units:
        wire["u"] = [
            [
                unit["qualname"],
                unit["start_line"],
                unit["end_line"],
                unit["loc"],
                unit["stmt_count"],
                unit["fingerprint"],
                unit["loc_bucket"],
                unit.get("cyclomatic_complexity", 1),
                unit.get("nesting_depth", 0),
                unit.get("risk", "low"),
                unit.get("raw_hash", ""),
                unit.get("entry_guard_count", 0),
                unit.get("entry_guard_terminal_profile", "none"),
                1 if unit.get("entry_guard_has_side_effect_before", False) else 0,
                unit.get("terminal_kind", "fallthrough"),
                unit.get("try_finally_profile", "none"),
                unit.get("side_effect_order_profile", "none"),
            ]
            for unit in units
        ]


def _encode_blocks(entry: CacheEntry, wire: dict[str, object]) -> None:
    blocks = sorted(
        entry["blocks"],
        key=lambda block: (
            block["qualname"],
            block["start_line"],
            block["end_line"],
            block["block_hash"],
        ),
    )
    if blocks:
        wire["b"] = [
            [
                block["qualname"],
                block["start_line"],
                block["end_line"],
                block["size"],
                block["block_hash"],
            ]
            for block in blocks
        ]


def _encode_segments(entry: CacheEntry, wire: dict[str, object]) -> None:
    segments = sorted(
        entry["segments"],
        key=lambda segment: (
            segment["qualname"],
            segment["start_line"],
            segment["end_line"],
            segment["segment_hash"],
        ),
    )
    if segments:
        wire["s"] = [
            [
                segment["qualname"],
                segment["start_line"],
                segment["end_line"],
                segment["size"],
                segment["segment_hash"],
                segment["segment_sig"],
            ]
            for segment in segments
        ]


def _append_coupled_classes_row(
    metric: ClassMetricsDict,
    *,
    rows: list[list[object]],
) -> None:
    coupled_classes = _normalized_optional_string_list(
        metric.get("coupled_classes", [])
    )
    if coupled_classes:
        rows.append([metric["qualname"], coupled_classes])


def _encode_class_metrics(entry: CacheEntry, wire: dict[str, object]) -> None:
    class_metrics = sorted(
        entry["class_metrics"],
        key=lambda metric: (
            metric["start_line"],
            metric["end_line"],
            metric["qualname"],
        ),
    )
    if class_metrics:
        coupled_classes_rows: list[list[object]] = []
        wire["cm"] = [
            [
                metric["qualname"],
                metric["start_line"],
                metric["end_line"],
                metric["cbo"],
                metric["lcom4"],
                metric["method_count"],
                metric["instance_var_count"],
                metric["risk_coupling"],
                metric["risk_cohesion"],
            ]
            for metric in class_metrics
        ]
        for metric in class_metrics:
            _append_coupled_classes_row(metric, rows=coupled_classes_rows)
        if coupled_classes_rows:
            wire["cc"] = coupled_classes_rows


def _encode_module_deps(entry: CacheEntry, wire: dict[str, object]) -> None:
    module_deps = sorted(
        entry["module_deps"],
        key=lambda dep: (dep["source"], dep["target"], dep["import_type"], dep["line"]),
    )
    if module_deps:
        wire["md"] = [
            [
                dep["source"],
                dep["target"],
                dep["import_type"],
                dep["line"],
            ]
            for dep in module_deps
        ]


def _encode_dead_candidates(entry: CacheEntry, wire: dict[str, object]) -> None:
    dead_candidates = sorted(
        entry["dead_candidates"],
        key=lambda candidate: (
            candidate["start_line"],
            candidate["end_line"],
            candidate["qualname"],
            candidate["local_name"],
            candidate["kind"],
        ),
    )
    if dead_candidates:
        encoded_dead_candidates: list[list[object]] = []
        for candidate in dead_candidates:
            encoded = [
                candidate["qualname"],
                candidate["local_name"],
                candidate["start_line"],
                candidate["end_line"],
                candidate["kind"],
            ]
            suppressed_rules = candidate.get("suppressed_rules", [])
            normalized_rules = _normalized_optional_string_list(suppressed_rules)
            if normalized_rules:
                encoded.append(normalized_rules)
            encoded_dead_candidates.append(encoded)
        wire["dc"] = encoded_dead_candidates


def _encode_name_lists(entry: CacheEntry, wire: dict[str, object]) -> None:
    if entry["referenced_names"]:
        wire["rn"] = sorted(set(entry["referenced_names"]))
    if entry.get("referenced_qualnames"):
        wire["rq"] = sorted(set(entry["referenced_qualnames"]))
    if entry["import_names"]:
        wire["in"] = sorted(set(entry["import_names"]))
    if entry["class_names"]:
        wire["cn"] = sorted(set(entry["class_names"]))


def _encode_security_surfaces(entry: CacheEntry, wire: dict[str, object]) -> None:
    security_surfaces = sorted(
        entry.get("security_surfaces", []),
        key=lambda item: (
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["category"],
            item["capability"],
            item["evidence_symbol"],
        ),
    )
    if security_surfaces:
        wire["sc"] = [
            [
                item["category"],
                item["capability"],
                item["module"],
                item["qualname"],
                item["start_line"],
                item["end_line"],
                item["location_scope"],
                item["classification_mode"],
                item["evidence_kind"],
                item["evidence_symbol"],
            ]
            for item in security_surfaces
        ]


def _encode_optional_metrics_sections(
    entry: CacheEntry, wire: dict[str, object]
) -> None:
    typing_coverage = entry.get("typing_coverage")
    if typing_coverage is not None:
        wire["tc"] = [
            typing_coverage["module"],
            typing_coverage["callable_count"],
            typing_coverage["params_total"],
            typing_coverage["params_annotated"],
            typing_coverage["returns_total"],
            typing_coverage["returns_annotated"],
            typing_coverage["any_annotation_count"],
        ]
    docstring_coverage = entry.get("docstring_coverage")
    if docstring_coverage is not None:
        wire["dg"] = [
            docstring_coverage["module"],
            docstring_coverage["public_symbol_total"],
            docstring_coverage["public_symbol_documented"],
        ]
    api_surface = entry.get("api_surface")
    if api_surface is not None:
        wire["as"] = [
            api_surface["module"],
            sorted(set(api_surface.get("all_declared", []))),
            [
                [
                    symbol["qualname"],
                    symbol["kind"],
                    symbol["start_line"],
                    symbol["end_line"],
                    symbol.get("exported_via", "name"),
                    symbol.get("returns_hash", ""),
                    [
                        [
                            param["name"],
                            param["kind"],
                            1 if param["has_default"] else 0,
                            param.get("annotation_hash", ""),
                        ]
                        for param in symbol.get("params", [])
                    ],
                ]
                for symbol in api_surface["symbols"]
            ],
        ]


def _encode_structural_findings(entry: CacheEntry, wire: dict[str, object]) -> None:
    if "structural_findings" in entry:
        structural_findings = entry.get("structural_findings", [])
        wire["sf"] = [
            [
                group["finding_kind"],
                group["finding_key"],
                sorted(group["signature"].items()),
                [
                    [item["qualname"], item["start"], item["end"]]
                    for item in group["items"]
                ],
            ]
            for group in structural_findings
        ]


def _encode_wire_file_entry(entry: CacheEntry) -> dict[str, object]:
    wire: dict[str, object] = {
        "st": [entry["stat"]["mtime_ns"], entry["stat"]["size"]],
    }
    _encode_source_stats(entry, wire)
    _encode_units(entry, wire)
    _encode_blocks(entry, wire)
    _encode_segments(entry, wire)
    _encode_class_metrics(entry, wire)
    _encode_module_deps(entry, wire)
    _encode_dead_candidates(entry, wire)
    _encode_name_lists(entry, wire)
    _encode_security_surfaces(entry, wire)
    _encode_optional_metrics_sections(entry, wire)
    _encode_structural_findings(entry, wire)
    return wire


__all__ = ["_encode_wire_file_entry"]
