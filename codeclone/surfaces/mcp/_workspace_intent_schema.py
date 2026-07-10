# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Compatibility exports for the surface-neutral intent registry schema."""

from __future__ import annotations

from ...workspace_intent.schema import (
    INTENT_REGISTRY_SCHEMA_VERSION,
    IntentRegistrySchemaError,
    create_schema_v1,
    ensure_schema,
    get_meta,
    open_intent_registry_db,
    open_intent_registry_db_readonly,
)

__all__ = [
    "INTENT_REGISTRY_SCHEMA_VERSION",
    "IntentRegistrySchemaError",
    "create_schema_v1",
    "ensure_schema",
    "get_meta",
    "open_intent_registry_db",
    "open_intent_registry_db_readonly",
]
