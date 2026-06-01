# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Public read-only workspace intent helpers."""

from __future__ import annotations

from .gate import (
    WorkspaceEditGateDecision,
    evaluate_workspace_edit_gate,
    has_authorized_workspace_intent,
    has_blocking_workspace_intent,
)

__all__ = [
    "WorkspaceEditGateDecision",
    "evaluate_workspace_edit_gate",
    "has_authorized_workspace_intent",
    "has_blocking_workspace_intent",
]
