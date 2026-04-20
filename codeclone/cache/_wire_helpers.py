# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Literal, TypeVar

from .entries import _as_risk_literal
from .integrity import (
    as_int_or_none as _as_int,
)
from .integrity import (
    as_object_list as _as_list,
)
from .integrity import (
    as_str_or_none as _as_str,
)
from .versioning import _DEFAULT_WIRE_UNIT_FLOW_PROFILES

_DecodedItemT = TypeVar("_DecodedItemT")


def _decode_wire_qualname_span(
    row: list[object],
) -> tuple[str, int, int] | None:
    qualname = _as_str(row[0])
    start_line = _as_int(row[1])
    end_line = _as_int(row[2])
    if qualname is None or start_line is None or end_line is None:
        return None
    return qualname, start_line, end_line


def _decode_wire_qualname_span_size(
    row: list[object],
) -> tuple[str, int, int, int] | None:
    qualname_span = _decode_wire_qualname_span(row)
    if qualname_span is None:
        return None
    size = _as_int(row[3])
    if size is None:
        return None
    qualname, start_line, end_line = qualname_span
    return qualname, start_line, end_line, size


def _decode_optional_wire_items(
    *,
    obj: dict[str, object],
    key: str,
    decode_item: Callable[[object], _DecodedItemT | None],
) -> list[_DecodedItemT] | None:
    raw_items = obj.get(key)
    if raw_items is None:
        return []
    wire_items = _as_list(raw_items)
    if wire_items is None:
        return None
    decoded_items: list[_DecodedItemT] = []
    for wire_item in wire_items:
        decoded = decode_item(wire_item)
        if decoded is None:
            return None
        decoded_items.append(decoded)
    return decoded_items


def _decode_optional_wire_items_for_filepath(
    *,
    obj: dict[str, object],
    key: str,
    filepath: str,
    decode_item: Callable[[object, str], _DecodedItemT | None],
) -> list[_DecodedItemT] | None:
    raw_items = obj.get(key)
    if raw_items is None:
        return []
    wire_items = _as_list(raw_items)
    if wire_items is None:
        return None
    decoded_items: list[_DecodedItemT] = []
    for wire_item in wire_items:
        decoded = decode_item(wire_item, filepath)
        if decoded is None:
            return None
        decoded_items.append(decoded)
    return decoded_items


def _decode_optional_wire_row(
    *,
    obj: dict[str, object],
    key: str,
    expected_len: int,
) -> list[object] | None:
    raw = obj.get(key)
    if raw is None:
        return None
    row = _as_list(raw)
    if row is None or len(row) != expected_len:
        return None
    return row


def _decode_optional_wire_names(
    *,
    obj: dict[str, object],
    key: str,
) -> list[str] | None:
    raw_names = obj.get(key)
    if raw_names is None:
        return []
    names = _as_list(raw_names)
    if names is None or not all(isinstance(name, str) for name in names):
        return None
    return [str(name) for name in names]


def _decode_optional_wire_coupled_classes(
    *,
    obj: dict[str, object],
    key: str,
) -> dict[str, list[str]] | None:
    raw = obj.get(key)
    if raw is None:
        return {}

    rows = _as_list(raw)
    if rows is None:
        return None

    decoded: dict[str, list[str]] = {}
    for wire_row in rows:
        row = _as_list(wire_row)
        if row is None or len(row) != 2:
            return None
        qualname = _as_str(row[0])
        names = _as_list(row[1])
        if qualname is None or names is None:
            return None
        if not all(isinstance(name, str) for name in names):
            return None
        decoded[qualname] = sorted({str(name) for name in names if str(name)})

    return decoded


def _decode_wire_row(
    value: object,
    *,
    valid_lengths: Collection[int],
) -> list[object] | None:
    row = _as_list(value)
    if row is None or len(row) not in valid_lengths:
        return None
    return row


def _decode_wire_named_span(
    value: object,
    *,
    valid_lengths: Collection[int],
) -> tuple[list[object], str, int, int] | None:
    row = _decode_wire_row(value, valid_lengths=valid_lengths)
    if row is None:
        return None
    span = _decode_wire_qualname_span(row)
    if span is None:
        return None
    qualname, start_line, end_line = span
    return row, qualname, start_line, end_line


def _decode_wire_named_sized_span(
    value: object,
    *,
    valid_lengths: Collection[int],
) -> tuple[list[object], str, int, int, int] | None:
    row = _decode_wire_row(value, valid_lengths=valid_lengths)
    if row is None:
        return None
    span = _decode_wire_qualname_span_size(row)
    if span is None:
        return None
    qualname, start_line, end_line, size = span
    return row, qualname, start_line, end_line, size


def _decode_wire_int_fields(
    row: list[object],
    *indexes: int,
) -> tuple[int, ...] | None:
    values: list[int] = []
    for index in indexes:
        value = _as_int(row[index])
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def _decode_wire_str_fields(
    row: list[object],
    *indexes: int,
) -> tuple[str, ...] | None:
    values: list[str] = []
    for index in indexes:
        value = _as_str(row[index])
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def _decode_wire_unit_core_fields(
    row: list[object],
) -> tuple[int, int, str, str, int, int, Literal["low", "medium", "high"], str] | None:
    int_fields = _decode_wire_int_fields(row, 3, 4, 7, 8)
    str_fields = _decode_wire_str_fields(row, 5, 6, 10)
    risk = _as_risk_literal(row[9])
    if int_fields is None or str_fields is None or risk is None:
        return None
    loc, stmt_count, cyclomatic_complexity, nesting_depth = int_fields
    fingerprint, loc_bucket, raw_hash = str_fields
    return (
        loc,
        stmt_count,
        fingerprint,
        loc_bucket,
        cyclomatic_complexity,
        nesting_depth,
        risk,
        raw_hash,
    )


def _decode_wire_unit_flow_profiles(
    row: list[object],
) -> tuple[int, str, bool, str, str, str] | None:
    if len(row) != 17:
        return _DEFAULT_WIRE_UNIT_FLOW_PROFILES

    parsed_entry_guard_count = _as_int(row[11])
    parsed_entry_guard_terminal_profile = _as_str(row[12])
    parsed_entry_guard_has_side_effect_before = _as_int(row[13])
    parsed_terminal_kind = _as_str(row[14])
    parsed_try_finally_profile = _as_str(row[15])
    parsed_side_effect_order_profile = _as_str(row[16])
    if (
        parsed_entry_guard_count is None
        or parsed_entry_guard_terminal_profile is None
        or parsed_entry_guard_has_side_effect_before is None
        or parsed_terminal_kind is None
        or parsed_try_finally_profile is None
        or parsed_side_effect_order_profile is None
    ):
        return None
    return (
        max(0, parsed_entry_guard_count),
        parsed_entry_guard_terminal_profile or "none",
        parsed_entry_guard_has_side_effect_before != 0,
        parsed_terminal_kind or "fallthrough",
        parsed_try_finally_profile or "none",
        parsed_side_effect_order_profile or "none",
    )


def _decode_wire_class_metric_fields(
    row: list[object],
) -> tuple[int, int, int, int, str, str] | None:
    int_fields = _decode_wire_int_fields(row, 3, 4, 5, 6)
    str_fields = _decode_wire_str_fields(row, 7, 8)
    if int_fields is None or str_fields is None:
        return None
    cbo, lcom4, method_count, instance_var_count = int_fields
    risk_coupling, risk_cohesion = str_fields
    return (
        cbo,
        lcom4,
        method_count,
        instance_var_count,
        risk_coupling,
        risk_cohesion,
    )


__all__ = [
    "_decode_optional_wire_coupled_classes",
    "_decode_optional_wire_items",
    "_decode_optional_wire_items_for_filepath",
    "_decode_optional_wire_names",
    "_decode_optional_wire_row",
    "_decode_wire_class_metric_fields",
    "_decode_wire_int_fields",
    "_decode_wire_named_sized_span",
    "_decode_wire_named_span",
    "_decode_wire_qualname_span",
    "_decode_wire_qualname_span_size",
    "_decode_wire_row",
    "_decode_wire_str_fields",
    "_decode_wire_unit_core_fields",
    "_decode_wire_unit_flow_profiles",
]
