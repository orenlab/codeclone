# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TYPE_CHECKING

from ...utils.coerce import as_int

if TYPE_CHECKING:
    from ...models import GroupItemsLike, GroupMap


def _group_items_by_key(
    items: GroupItemsLike,
    *,
    key_name: str,
) -> GroupMap:
    grouped: GroupMap = {}
    for item in items:
        grouped.setdefault(str(item[key_name]), []).append(dict(item))
    return grouped


def _filter_groups_by_size(
    groups: GroupMap,
    *,
    min_occurrences: int,
) -> GroupMap:
    return {
        group_key: grouped_items
        for group_key, grouped_items in groups.items()
        if len(grouped_items) >= min_occurrences
    }


def is_clone_eligible(
    *,
    loc: int,
    stmt_count: int,
    min_loc: int,
    min_stmt: int,
) -> bool:
    """Return whether a unit of this shape may enter the function clone lane.

    Clone eligibility contract (39Y Y5): the ``min_loc`` / ``min_stmt`` floors
    are a *clone-lane* predicate. They decide which units are large enough for
    a duplicate to be worth reporting; they never decide which functions carry
    metric facts. This module is the single owner of the predicate — the
    extractor gates blocks, segments and structural findings on it, and the
    clone lane filters with it — so the two lanes cannot drift apart.
    """

    return loc >= min_loc and stmt_count >= min_stmt


def clone_eligible_units(
    units: GroupItemsLike,
    *,
    min_loc: int,
    min_stmt: int,
) -> list[dict[str, object]]:
    """Reduce emitted unit facts to the clone lane's population.

    Unit facts exist for every defined function, so the clone lane applies its
    floors here instead of at fact emission. Eligibility is re-derived from the
    ``loc`` / ``stmt_count`` each unit already carries, which is what keeps a
    warm (cache-served) run identical to a cold one.
    """

    return [
        dict(unit)
        for unit in units
        if is_clone_eligible(
            loc=as_int(unit["loc"]),
            stmt_count=as_int(unit["stmt_count"]),
            min_loc=min_loc,
            min_stmt=min_stmt,
        )
    ]


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
    signature_groups = _filter_groups_by_size(
        _group_items_by_key(segments, key_name="segment_sig"),
        min_occurrences=min_occurrences,
    )

    confirmed: GroupMap = {}
    for items in signature_groups.values():
        hash_groups = _filter_groups_by_size(
            _group_items_by_key(items, key_name="segment_hash"),
            min_occurrences=min_occurrences,
        )

        for segment_hash, hash_items in hash_groups.items():
            by_function: GroupMap = {}
            for item in hash_items:
                by_function.setdefault(str(item["qualname"]), []).append(item)

            for qualname, q_items in by_function.items():
                if len(q_items) >= min_occurrences:
                    confirmed[f"{segment_hash}|{qualname}"] = q_items

    return confirmed
