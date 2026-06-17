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


def _denial_payload(
    *,
    workspace_root: str,
    target_path: str,
    enforce_scope: str,
    blocked_kind: str,
) -> dict[str, object]:
    return change_control_denial_payload(
        workspace_root=workspace_root,
        target_path=target_path,
        enforce_scope=enforce_scope,
        blocked_kind=blocked_kind,
    )


def main() -> None:
    payload: dict[str, object] | None = None
    data = parse_hook_input(read_bounded_stdin())
    if data is None:
        return emit_hook_payload(payload)

    workspace_root = workspace_root_from_hook(data)
    if not workspace_root:
        return emit_hook_payload(payload)

    repo_root = Path(workspace_root)
    enforce_scope = resolve_enforce_scope(repo_root)
    try:
        gate_decision = evaluate_workspace_intent_gate(repo_root)
    except WorkspaceIntentGateUnavailable as exc:
        return emit_hook_payload(
            _denial_payload(
                workspace_root=workspace_root,
                target_path=str(exc) or "CodeClone gate API unavailable",
                enforce_scope=enforce_scope,
                blocked_kind="registry",
            )
        )
    if gate_decision.allowed:
        return emit_hook_payload(payload)

    tool_name = str(data.get("tool_name", ""))
    blocked_kind: str | None = None
    blocked_target: str | None = None
    blocked = False

    if tool_name == "Shell":
        blocked_kind = "shell"
        blocked_target = shell_command_from_hook(data)
        blocked = should_gate_shell_command(command=blocked_target)
    elif tool_name in _WRITE_TOOLS:
        blocked_kind = "file"
        blocked_target = edited_path_from_pre_tool_use(data)
        blocked = bool(blocked_target) and should_gate_edit_path(
            target_path=blocked_target,
            workspace_root=workspace_root,
            enforce_scope=enforce_scope,
        )

    if blocked and blocked_kind and blocked_target:
        payload = _denial_payload(
            workspace_root=workspace_root,
            target_path=blocked_target,
            enforce_scope=enforce_scope,
            blocked_kind=blocked_kind,
        )

    emit_hook_payload(payload)


if __name__ == "__main__":
    main()
