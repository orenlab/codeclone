# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from ...controller_insights import (
    controller_audit_trail_payload,
    workspace_session_stats_payload,
)
from ...memory.ide_governance import IdeGovernanceSessionState
from . import _session_helpers as _helpers
from ._session_shared import MCPServiceContractError

IDE_INSIGHTS_UNAVAILABLE_MESSAGE = (
    "This tool is only available through the CodeClone VS Code extension "
    "(MCP server launched with --ide-governance-channel). Agents must use "
    "manage_change_intent(action='list_workspace') for coordination state."
)
IDE_INSIGHTS_UNAVAILABLE_NEXT_STEP = (
    "Connect with the CodeClone VS Code extension or run "
    "codeclone . --session-stats / --audit in the terminal."
)


class _MCPSessionInsightsMixin:
    _ide_governance: IdeGovernanceSessionState

    def _require_ide_insights_channel(self, *, tool_name: str) -> None:
        if not self._ide_governance.channel_enabled:
            raise MCPServiceContractError(
                f"{tool_name} is IDE-only. {IDE_INSIGHTS_UNAVAILABLE_MESSAGE} "
                f"{IDE_INSIGHTS_UNAVAILABLE_NEXT_STEP}"
            )

    def get_workspace_session_stats(self, *, root: str) -> dict[str, object]:
        self._require_ide_insights_channel(tool_name="get_workspace_session_stats")
        root_path = _helpers._resolve_root(root)
        try:
            payload = workspace_session_stats_payload(root_path)
        except Exception as exc:
            raise MCPServiceContractError(
                f"Failed to read workspace session stats: {exc}"
            ) from exc
        return {"tool": "get_workspace_session_stats", **payload}

    def get_controller_audit_trail(
        self,
        *,
        root: str,
        limit: int = 50,
        audit_path: str | None = None,
    ) -> dict[str, object]:
        self._require_ide_insights_channel(tool_name="get_controller_audit_trail")
        root_path = _helpers._resolve_root(root)
        if limit < 1 or limit > 200:
            raise MCPServiceContractError(
                "limit must be between 1 and 200 for get_controller_audit_trail."
            )
        payload = controller_audit_trail_payload(
            Path(root_path),
            limit=limit,
            audit_path_value=audit_path,
        )
        return {"tool": "get_controller_audit_trail", **payload}
