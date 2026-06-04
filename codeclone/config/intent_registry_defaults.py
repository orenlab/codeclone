# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Final, Literal

from ..contracts import DOCS_URL

IntentRegistryBackend = Literal["file", "sqlite"]

DEFAULT_INTENT_REGISTRY_BACKEND: Final[IntentRegistryBackend] = "file"
DEFAULT_INTENT_REGISTRY_DB_PATH: Final = ".codeclone/db/intents.sqlite3"
DEFAULT_INTENT_REGISTRY_RETENTION_DAYS: Final = 7
MIN_INTENT_REGISTRY_RETENTION_DAYS: Final = 1
MAX_INTENT_REGISTRY_RETENTION_DAYS: Final = 14
INTENT_REGISTRY_RETENTION_PLANS_DOC: Final = f"{DOCS_URL}plans-and-retention/"
INTENT_REGISTRY_RETENTION_ENTERPRISE_MESSAGE: Final = (
    "intent_registry_retention_days cannot exceed 14 days in the open-source "
    f"edition; see {INTENT_REGISTRY_RETENTION_PLANS_DOC} for CodeClone Team and "
    "Enterprise retention limits, premium support, and contact details."
)

__all__ = [
    "DEFAULT_INTENT_REGISTRY_BACKEND",
    "DEFAULT_INTENT_REGISTRY_DB_PATH",
    "DEFAULT_INTENT_REGISTRY_RETENTION_DAYS",
    "INTENT_REGISTRY_RETENTION_ENTERPRISE_MESSAGE",
    "INTENT_REGISTRY_RETENTION_PLANS_DOC",
    "MAX_INTENT_REGISTRY_RETENTION_DAYS",
    "MIN_INTENT_REGISTRY_RETENTION_DAYS",
    "IntentRegistryBackend",
]
