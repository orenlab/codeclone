# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path


def bool_attr(obj: object, name: str) -> bool:
    return bool(getattr(obj, name, False))


def int_attr(obj: object, name: str, default: int = 0) -> int:
    value = getattr(obj, name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def optional_text_attr(obj: object, name: str) -> str | None:
    value = getattr(obj, name, None)
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return value
    return None


def text_attr(obj: object, name: str, default: str = "") -> str:
    value = optional_text_attr(obj, name)
    return default if value is None else value


def set_bool_attr(obj: object, name: str, value: bool) -> None:
    setattr(obj, name, value)
