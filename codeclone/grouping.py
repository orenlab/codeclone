# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import GroupItemsLike, GroupMap


def build_groups(units: GroupItemsLike) -> GroupMap:
    groups: GroupMap = {}
    for unit in units:
        fingerprint = str(unit["fingerprint"])
        loc_bucket = str(unit["loc_bucket"])
        key = f"{fingerprint}|{loc_bucket}"
        groups.setdefault(key, []).append(dict(unit))
    return {group_key: items for group_key, items in groups.items() if len(items) > 1}


def build_block_groups(blocks: GroupItemsLike, min_functions: int = 2) -> GroupMap:
    groups: GroupMap = {}
    for block in blocks:
        groups.setdefault(str(block["block_hash"]), []).append(dict(block))

    filtered: GroupMap = {}
    for block_hash, items in groups.items():
        functions = {str(item["qualname"]) for item in items}
        if len(functions) >= min_functions:
            filtered[block_hash] = items

    return filtered


def build_segment_groups(
    segments: GroupItemsLike, min_occurrences: int = 2
) -> GroupMap:
    signature_groups: GroupMap = {}
    for segment in segments:
        signature_groups.setdefault(
            str(segment["segment_sig"]),
            [],
        ).append(dict(segment))

    confirmed: GroupMap = {}
    for items in signature_groups.values():
        if len(items) < min_occurrences:
            continue

        hash_groups: GroupMap = {}
        for item in items:
            hash_groups.setdefault(str(item["segment_hash"]), []).append(dict(item))

        for segment_hash, hash_items in hash_groups.items():
            if len(hash_items) < min_occurrences:
                continue

            by_function: GroupMap = {}
            for item in hash_items:
                by_function.setdefault(str(item["qualname"]), []).append(item)

            for qualname, q_items in by_function.items():
                if len(q_items) >= min_occurrences:
                    confirmed[f"{segment_hash}|{qualname}"] = q_items

    return confirmed
