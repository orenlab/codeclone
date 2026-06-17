# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final

ANALYTICS_NESTED_TABLE_KEY: Final = "analytics"

ANALYTICS_PATH_CONFIG_KEYS: Final = frozenset(
    {
        "db_path",
        "vectors_path",
        "embedding_cache_dir",
    }
)

__all__ = [
    "ANALYTICS_NESTED_TABLE_KEY",
    "ANALYTICS_PATH_CONFIG_KEYS",
]
