# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Compatibility exports for the surface-neutral workspace intent contract."""

from __future__ import annotations

from ...workspace_intent.contract import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_TTL_SECONDS,
    LEGACY_REGISTRY_VERSION,
    MAX_LEASE_SECONDS,
    MAX_TTL_SECONDS,
    MIN_LEASE_SECONDS,
    MIN_TTL_SECONDS,
    REGISTRY_VERSION,
    BeforeExecutionWitness,
    WorkspaceIntentRecord,
    compute_intent_digest,
    compute_scope_digest,
    verify_intent_integrity,
)

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "LEGACY_REGISTRY_VERSION",
    "MAX_LEASE_SECONDS",
    "MAX_TTL_SECONDS",
    "MIN_LEASE_SECONDS",
    "MIN_TTL_SECONDS",
    "REGISTRY_VERSION",
    "BeforeExecutionWitness",
    "WorkspaceIntentRecord",
    "compute_intent_digest",
    "compute_scope_digest",
    "verify_intent_integrity",
]
