"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from typing import Any

from ._report_types import GroupItem, GroupMap


def _coerce_positive_int(value: Any) -> int | None:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    return integer if integer > 0 else None


def _block_item_sort_key(item: GroupItem) -> tuple[str, str, int, int]:
    start_line = _coerce_positive_int(item.get("start_line")) or 0
    end_line = _coerce_positive_int(item.get("end_line")) or 0
    return (
        str(item.get("filepath", "")),
        str(item.get("qualname", "")),
        start_line,
        end_line,
    )


def _merge_block_items(items: list[GroupItem]) -> list[GroupItem]:
    """
    Merge overlapping/adjacent block windows into maximal ranges per function.
    """
    if not items:
        return []

    sorted_items = sorted(items, key=_block_item_sort_key)
    merged: list[GroupItem] = []
    current: GroupItem | None = None

    for item in sorted_items:
        start_line = _coerce_positive_int(item.get("start_line"))
        end_line = _coerce_positive_int(item.get("end_line"))
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
        if same_owner and start_line <= int(current["end_line"]) + 1:
            current["end_line"] = max(int(current["end_line"]), end_line)
            current["size"] = max(
                1, int(current["end_line"]) - int(current["start_line"]) + 1
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


def prepare_block_report_groups(block_groups: GroupMap) -> GroupMap:
    """
    Convert sliding block windows into maximal merged regions for reporting.
    Block hash keys remain unchanged.
    """
    prepared: GroupMap = {}
    for key, items in block_groups.items():
        merged = _merge_block_items(items)
        if merged:
            prepared[key] = merged
        else:
            prepared[key] = sorted(items, key=_block_item_sort_key)
    return prepared
