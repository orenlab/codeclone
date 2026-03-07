"""Block clone report preparation."""

from __future__ import annotations

from .merge import coerce_positive_int, merge_overlapping_items
from .types import GroupItem, GroupItemLike, GroupItemsLike, GroupMap, GroupMapLike


def block_item_sort_key(item: GroupItemLike) -> tuple[str, str, int, int]:
    start_line = coerce_positive_int(item.get("start_line")) or 0
    end_line = coerce_positive_int(item.get("end_line")) or 0
    return (
        str(item.get("filepath", "")),
        str(item.get("qualname", "")),
        start_line,
        end_line,
    )


def merge_block_items(items: GroupItemsLike) -> list[GroupItem]:
    return merge_overlapping_items(items, sort_key=block_item_sort_key)


def prepare_block_report_groups(block_groups: GroupMapLike) -> GroupMap:
    """
    Convert sliding block windows into maximal merged regions for reporting.
    Block hash keys remain unchanged.
    """
    prepared: GroupMap = {}
    for key, items in block_groups.items():
        merged = merge_block_items(items)
        if merged:
            prepared[key] = merged
        else:
            prepared[key] = [
                dict(item) for item in sorted(items, key=block_item_sort_key)
            ]
    return prepared
