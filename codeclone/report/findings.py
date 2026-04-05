# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic structural-finding helpers for the report layer.

HTML rendering lives in ``codeclone._html_report._sections._structural``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models import StructuralFindingOccurrence


def _sort_key_item(
    occurrence: StructuralFindingOccurrence,
) -> tuple[str, str, int, int]:
    return (
        occurrence.file_path,
        occurrence.qualname,
        occurrence.start,
        occurrence.end,
    )


def _dedupe_items(
    items: Sequence[StructuralFindingOccurrence],
) -> tuple[StructuralFindingOccurrence, ...]:
    unique: dict[tuple[str, str, int, int], StructuralFindingOccurrence] = {}
    for item in sorted(items, key=_sort_key_item):
        key = (item.file_path, item.qualname, item.start, item.end)
        if key not in unique:
            unique[key] = item
    return tuple(unique.values())


def _spread(items: Sequence[StructuralFindingOccurrence]) -> dict[str, int]:
    files: set[str] = set()
    functions: set[str] = set()
    for item in items:
        files.add(item.file_path)
        functions.add(item.qualname)
    return {"files": len(files), "functions": len(functions)}


def _finding_scope_text(items: Sequence[StructuralFindingOccurrence]) -> str:
    spread = _spread(items)
    if spread["functions"] == 1:
        return f"inside {items[0].qualname}"
    return (
        f"across {spread['functions']} functions in {spread['files']} "
        f"{'file' if spread['files'] == 1 else 'files'}"
    )
