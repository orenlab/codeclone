# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Public read-only workspace intent helpers."""

from __future__ import annotations

from .gate import (
    UnclosedWorkspaceIntent,
    WorkspaceEditGateDecision,
    WorkspaceIntentRegistryUnavailable,
    evaluate_workspace_edit_gate,
    has_authorized_workspace_intent,
    has_blocking_workspace_intent,
    list_unclosed_workspace_intents,
    list_unclosed_workspace_intents_for_hook_cleanup,
)

__all__ = [
    "UnclosedWorkspaceIntent",
    "WorkspaceEditGateDecision",
    "WorkspaceIntentRegistryUnavailable",
    "evaluate_workspace_edit_gate",
    "has_authorized_workspace_intent",
    "has_blocking_workspace_intent",
    "list_unclosed_workspace_intents",
    "list_unclosed_workspace_intents_for_hook_cleanup",
]
