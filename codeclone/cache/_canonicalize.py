# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Small deterministic normalizers shared by the cache-v3 codec."""

from __future__ import annotations


def _normalized_optional_string_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        strings.append(item)
    return sorted(set(strings))


__all__ = ["_normalized_optional_string_list"]
