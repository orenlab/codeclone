# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeGuard

__all__ = [
    "dict_items_from_list",
    "is_payload_dict",
    "is_record_mapping",
    "mapping_items_from_list",
    "nested_payload_dict",
]


def is_payload_dict(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def is_record_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def mapping_items_from_list(values: object) -> list[Mapping[str, object]]:
    if not isinstance(values, list):
        return []
    return [item for item in values if is_record_mapping(item)]


def dict_items_from_list(values: object) -> list[dict[str, object]]:
    if not isinstance(values, list):
        return []
    return [item for item in values if is_payload_dict(item)]


def nested_payload_dict(value: object) -> dict[str, object]:
    if is_payload_dict(value):
        return value
    return {}
