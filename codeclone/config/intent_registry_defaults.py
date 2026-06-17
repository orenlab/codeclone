# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final, Literal

IntentRegistryBackend = Literal["file", "sqlite"]

DEFAULT_INTENT_REGISTRY_BACKEND: Final[IntentRegistryBackend] = "file"
DEFAULT_INTENT_REGISTRY_DB_PATH: Final = ".codeclone/db/intents.sqlite3"
# Closed-row retention for the SQLite intent registry. A sensible local default;
# there is no edition cap — operators may set any positive number of days.
DEFAULT_INTENT_REGISTRY_RETENTION_DAYS: Final = 14
MIN_INTENT_REGISTRY_RETENTION_DAYS: Final = 1

__all__ = [
    "DEFAULT_INTENT_REGISTRY_BACKEND",
    "DEFAULT_INTENT_REGISTRY_DB_PATH",
    "DEFAULT_INTENT_REGISTRY_RETENTION_DAYS",
    "MIN_INTENT_REGISTRY_RETENTION_DAYS",
    "IntentRegistryBackend",
]
