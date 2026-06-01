#!/usr/bin/env python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""preToolUse gate — deny writes without a workspace change intent.

Without intent, direct repository file writes are blocked, including ``.git/**``.
Only read-only Git inspection shell commands are allowed. Scopes: ``python``
(``.py``/``.pyi``) or ``repo`` (workspace tree).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_io import (
    WorkspaceIntentGateUnavailable,
    change_control_denial_payload,
    edited_path_from_pre_tool_use,
    emit_hook_payload,
    evaluate_workspace_intent_gate,
    parse_hook_input,
    read_bounded_stdin,
    resolve_enforce_scope,
    shell_command_from_hook,
    should_gate_edit_path,
    should_gate_shell_command,
    workspace_root_from_hook,
)

_WRITE_TOOLS = frozenset({"Write", "StrReplace", "ApplyPatch"})


def main() -> None:
    payload: dict[str, object] | None = None
    data = parse_hook_input(read_bounded_stdin())
    if data is None:
        emit_hook_payload(payload)
        return

    workspace_root = workspace_root_from_hook(data)
    if not workspace_root:
        emit_hook_payload(payload)
        return

    repo_root = Path(workspace_root)
    enforce_scope = resolve_enforce_scope(repo_root)
    try:
        gate_decision = evaluate_workspace_intent_gate(repo_root)
    except WorkspaceIntentGateUnavailable as exc:
        emit_hook_payload(
            change_control_denial_payload(
                workspace_root=workspace_root,
                target_path=str(exc) or "CodeClone gate API unavailable",
                enforce_scope=enforce_scope,
                blocked_kind="registry",
            )
        )
        return
    if gate_decision.allowed:
        emit_hook_payload(payload)
        return

    tool_name = str(data.get("tool_name", ""))

    if tool_name == "Shell":
        command = shell_command_from_hook(data)
        if should_gate_shell_command(command=command):
            payload = change_control_denial_payload(
                workspace_root=workspace_root,
                target_path=command,
                enforce_scope=enforce_scope,
                blocked_kind="shell",
            )
    elif tool_name in _WRITE_TOOLS:
        target_path = edited_path_from_pre_tool_use(data)
        if target_path and should_gate_edit_path(
            target_path=target_path,
            workspace_root=workspace_root,
            enforce_scope=enforce_scope,
        ):
            payload = change_control_denial_payload(
                workspace_root=workspace_root,
                target_path=target_path,
                enforce_scope=enforce_scope,
                blocked_kind="file",
            )

    emit_hook_payload(payload)


if __name__ == "__main__":
    main()
