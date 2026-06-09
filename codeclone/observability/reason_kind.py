# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic classifier for why an expensive maintenance span ran.

Free-text ``reason`` is optional; ``reason_kind`` is the closed, deterministic
vocabulary. ``unknown`` on an expensive semantic/trajectory span is a red flag
(aggregated by the read model as ``unknown_expensive_rebuild_count``).
"""

from __future__ import annotations

from typing import Literal

ReasonKind = Literal[
    "content_changed",
    "schema_version_changed",
    "model_changed",
    "manual_rebuild",
    "first_index",
    "unknown",
]

REASON_KINDS: frozenset[str] = frozenset(
    {
        "content_changed",
        "schema_version_changed",
        "model_changed",
        "manual_rebuild",
        "first_index",
        "unknown",
    }
)


def validate_reason_kind(value: str | None) -> str | None:
    if value is None or value in REASON_KINDS:
        return value
    msg = f"unknown reason_kind: {value!r}"
    raise ValueError(msg)


__all__ = ["REASON_KINDS", "ReasonKind", "validate_reason_kind"]
