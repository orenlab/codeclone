# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ..domain.source_scope import SOURCE_KIND_BREAKDOWN_KEYS
from ..models import SecuritySurface
from ..paths import classify_source_kind


def _security_surface_source_kind(
    surface: SecuritySurface,
    *,
    scan_root: str,
) -> str:
    return classify_source_kind(surface.filepath, scan_root=scan_root)


def _security_surface_sort_key(
    surface: SecuritySurface,
    *,
    scan_root: str,
) -> tuple[str, int, int, str, str, str, str]:
    source_kind = _security_surface_source_kind(surface, scan_root=scan_root)
    return (
        source_kind,
        surface.start_line,
        surface.end_line,
        surface.filepath,
        surface.qualname,
        surface.category,
        surface.capability,
    )


def build_security_surfaces_payload(
    *,
    scan_root: str,
    surfaces: Sequence[SecuritySurface],
) -> dict[str, object]:
    sorted_surfaces = tuple(
        sorted(
            surfaces,
            key=lambda surface: _security_surface_sort_key(
                surface,
                scan_root=scan_root,
            ),
        )
    )
    category_counts = Counter(surface.category for surface in sorted_surfaces)
    source_kind_counts = Counter(
        _security_surface_source_kind(surface, scan_root=scan_root)
        for surface in sorted_surfaces
    )
    return {
        "summary": {
            "items": len(sorted_surfaces),
            "modules": len({surface.module for surface in sorted_surfaces}),
            "exact_items": len(sorted_surfaces),
            "category_count": len(category_counts),
            "categories": {
                category: category_counts[category]
                for category in sorted(category_counts)
            },
            "by_source_kind": {
                kind: source_kind_counts.get(kind, 0)
                for kind in SOURCE_KIND_BREAKDOWN_KEYS
            },
            "production": source_kind_counts.get("production", 0),
            "tests": source_kind_counts.get("tests", 0),
            "fixtures": source_kind_counts.get("fixtures", 0),
            "other": source_kind_counts.get("other", 0),
            "report_only": True,
        },
        "items": [
            {
                "category": surface.category,
                "capability": surface.capability,
                "module": surface.module,
                "filepath": surface.filepath,
                "qualname": surface.qualname,
                "start_line": surface.start_line,
                "end_line": surface.end_line,
                "source_kind": _security_surface_source_kind(
                    surface,
                    scan_root=scan_root,
                ),
                "location_scope": surface.location_scope,
                "classification_mode": surface.classification_mode,
                "evidence_kind": surface.evidence_kind,
                "evidence_symbol": surface.evidence_symbol,
            }
            for surface in sorted_surfaces
        ],
    }


__all__ = ["build_security_surfaces_payload"]
