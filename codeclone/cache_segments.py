# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypedDict

from .cache_io import (
    as_int_or_none,
    as_object_list,
    as_str_dict,
    as_str_or_none,
)
from .cache_paths import runtime_filepath_from_wire, wire_filepath_from_runtime
from .models import SegmentGroupItem

SegmentDict = SegmentGroupItem


class SegmentReportProjection(TypedDict):
    digest: str
    suppressed: int
    groups: dict[str, list[SegmentDict]]


def build_segment_report_projection(
    *,
    digest: str,
    suppressed: int,
    groups: Mapping[str, Sequence[Mapping[str, object]]],
) -> SegmentReportProjection:
    normalized_groups: dict[str, list[SegmentDict]] = {}
    for group_key in sorted(groups):
        normalized_items: list[SegmentDict] = []
        for raw_item in sorted(
            groups[group_key],
            key=lambda item: (
                str(item.get("filepath", "")),
                str(item.get("qualname", "")),
                as_int_or_none(item.get("start_line")) or 0,
                as_int_or_none(item.get("end_line")) or 0,
            ),
        ):
            segment_hash = as_str_or_none(raw_item.get("segment_hash"))
            segment_sig = as_str_or_none(raw_item.get("segment_sig"))
            filepath = as_str_or_none(raw_item.get("filepath"))
            qualname = as_str_or_none(raw_item.get("qualname"))
            start_line = as_int_or_none(raw_item.get("start_line"))
            end_line = as_int_or_none(raw_item.get("end_line"))
            size = as_int_or_none(raw_item.get("size"))
            if (
                segment_hash is None
                or segment_sig is None
                or filepath is None
                or qualname is None
                or start_line is None
                or end_line is None
                or size is None
            ):
                continue
            normalized_items.append(
                SegmentGroupItem(
                    segment_hash=segment_hash,
                    segment_sig=segment_sig,
                    filepath=filepath,
                    qualname=qualname,
                    start_line=start_line,
                    end_line=end_line,
                    size=size,
                )
            )
        if normalized_items:
            normalized_groups[group_key] = normalized_items
    return {
        "digest": digest,
        "suppressed": max(0, int(suppressed)),
        "groups": normalized_groups,
    }


def decode_segment_report_projection(
    value: object,
    *,
    root: Path | None,
) -> SegmentReportProjection | None:
    obj = as_str_dict(value)
    if obj is None:
        return None
    digest = as_str_or_none(obj.get("d"))
    suppressed = as_int_or_none(obj.get("s"))
    groups_raw = as_object_list(obj.get("g"))
    if digest is None or suppressed is None or groups_raw is None:
        return None
    groups: dict[str, list[SegmentDict]] = {}
    for group_row in groups_raw:
        group_list = as_object_list(group_row)
        if group_list is None or len(group_list) != 2:
            return None
        group_key = as_str_or_none(group_list[0])
        items_raw = as_object_list(group_list[1])
        if group_key is None or items_raw is None:
            return None
        items: list[SegmentDict] = []
        for item_raw in items_raw:
            item_list = as_object_list(item_raw)
            if item_list is None or len(item_list) != 7:
                return None
            wire_filepath = as_str_or_none(item_list[0])
            qualname = as_str_or_none(item_list[1])
            start_line = as_int_or_none(item_list[2])
            end_line = as_int_or_none(item_list[3])
            size = as_int_or_none(item_list[4])
            segment_hash = as_str_or_none(item_list[5])
            segment_sig = as_str_or_none(item_list[6])
            if (
                wire_filepath is None
                or qualname is None
                or start_line is None
                or end_line is None
                or size is None
                or segment_hash is None
                or segment_sig is None
            ):
                return None
            items.append(
                SegmentGroupItem(
                    segment_hash=segment_hash,
                    segment_sig=segment_sig,
                    filepath=runtime_filepath_from_wire(wire_filepath, root=root),
                    qualname=qualname,
                    start_line=start_line,
                    end_line=end_line,
                    size=size,
                )
            )
        groups[group_key] = items
    return {
        "digest": digest,
        "suppressed": max(0, suppressed),
        "groups": groups,
    }


def encode_segment_report_projection(
    projection: SegmentReportProjection | None,
    *,
    root: Path | None,
) -> dict[str, object] | None:
    if projection is None:
        return None
    groups_rows: list[list[object]] = []
    for group_key in sorted(projection["groups"]):
        items = sorted(
            projection["groups"][group_key],
            key=lambda item: (
                item["filepath"],
                item["qualname"],
                item["start_line"],
                item["end_line"],
            ),
        )
        encoded_items = [
            [
                wire_filepath_from_runtime(item["filepath"], root=root),
                item["qualname"],
                item["start_line"],
                item["end_line"],
                item["size"],
                item["segment_hash"],
                item["segment_sig"],
            ]
            for item in items
        ]
        groups_rows.append([group_key, encoded_items])
    return {
        "d": projection["digest"],
        "s": max(0, int(projection["suppressed"])),
        "g": groups_rows,
    }
