# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.workspace_intent.gate import (
    WorkspaceEditGateDecision,
    evaluate_workspace_edit_gate,
)


def assert_gate_denied(
    root: Path,
    *,
    reason: str,
) -> WorkspaceEditGateDecision:
    decision = evaluate_workspace_edit_gate(root)
    assert decision.allowed is False
    assert decision.reason == reason
    return decision
