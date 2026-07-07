# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping

from .exceptions import AnalyticsWorkflowError


def copy_str_key_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    mapping: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise AnalyticsWorkflowError("analytics mapping contains non-string key")
        mapping[key] = item
    return mapping
