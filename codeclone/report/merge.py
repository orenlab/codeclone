# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from .types import GroupItem, GroupItemLike, GroupItemsLike


def coerce_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        integer = int(value)
    elif isinstance(value, int):
        integer = value
    elif isinstance(value, str):
        try:
            integer = int(value)
        except ValueError:
            return None
    else:
        return None
    return integer if integer > 0 else None


def merge_overlapping_items(
    items: GroupItemsLike,
    *,
    sort_key: Callable[[GroupItemLike], tuple[str, str, int, int]],
) -> list[GroupItem]:
    """Merge overlapping or adjacent ranges for the same file/function pair."""
    if not items:
        return []

    sorted_items = sorted(items, key=sort_key)
    merged: list[GroupItem] = []
    current: GroupItem | None = None

    for item in sorted_items:
        start_line = coerce_positive_int(item.get("start_line"))
        end_line = coerce_positive_int(item.get("end_line"))
        if start_line is None or end_line is None or end_line < start_line:
            continue

        if current is None:
            current = dict(item)
            current["start_line"] = start_line
            current["end_line"] = end_line
            current["size"] = max(1, end_line - start_line + 1)
            continue

        same_owner = str(current.get("filepath", "")) == str(
            item.get("filepath", "")
        ) and str(current.get("qualname", "")) == str(item.get("qualname", ""))
        current_end = coerce_positive_int(current.get("end_line")) or 0
        current_start = coerce_positive_int(current.get("start_line")) or current_end
        if same_owner and start_line <= current_end + 1:
            merged_end = max(current_end, end_line)
            current["end_line"] = merged_end
            current["size"] = max(
                1,
                merged_end - current_start + 1,
            )
            continue

        merged.append(current)
        current = dict(item)
        current["start_line"] = start_line
        current["end_line"] = end_line
        current["size"] = max(1, end_line - start_line + 1)

    if current is not None:
        merged.append(current)

    return merged
