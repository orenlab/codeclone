"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from ._report_types import GroupItem, GroupMap


def build_groups(units: list[GroupItem]) -> GroupMap:
    groups: GroupMap = {}
    for u in units:
        key = f"{u['fingerprint']}|{u['loc_bucket']}"
        groups.setdefault(key, []).append(u)
    return {k: v for k, v in groups.items() if len(v) > 1}


def build_block_groups(blocks: list[GroupItem], min_functions: int = 2) -> GroupMap:
    groups: GroupMap = {}
    for b in blocks:
        groups.setdefault(b["block_hash"], []).append(b)

    filtered: GroupMap = {}
    for h, items in groups.items():
        functions = {i["qualname"] for i in items}
        if len(functions) >= min_functions:
            filtered[h] = items

    return filtered


def build_segment_groups(
    segments: list[GroupItem], min_occurrences: int = 2
) -> GroupMap:
    sig_groups: GroupMap = {}
    for s in segments:
        sig_groups.setdefault(s["segment_sig"], []).append(s)

    confirmed: GroupMap = {}
    for items in sig_groups.values():
        if len(items) < min_occurrences:
            continue

        hash_groups: GroupMap = {}
        for item in items:
            hash_groups.setdefault(item["segment_hash"], []).append(item)

        for segment_hash, hash_items in hash_groups.items():
            if len(hash_items) < min_occurrences:
                continue

            by_func: GroupMap = {}
            for it in hash_items:
                by_func.setdefault(it["qualname"], []).append(it)

            for qualname, q_items in by_func.items():
                if len(q_items) >= min_occurrences:
                    confirmed[f"{segment_hash}|{qualname}"] = q_items

    return confirmed
