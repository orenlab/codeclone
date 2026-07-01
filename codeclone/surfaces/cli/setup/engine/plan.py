# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Read-only setup plan projection (pyproject and gitignore previews)."""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path
from typing import Literal

from .....config.pyproject_loader import open_repo_config
from .....config.pyproject_writer import PyprojectWriterError, merge_tool_codeclone
from .....contracts import DEFAULT_BASELINE_PATH
from .....paths.gitignore import (
    GITIGNORE_CODECLONE_CACHE_SUGGESTED_ENTRY,
    append_gitignore_line,
)
from .....utils.json_io import json_text
from .capabilities import DiscoverContext
from .discover import build_discover_context

PlanStatus = Literal["empty", "ready", "blocked"]


def build_setup_plan(root_path: Path) -> dict[str, object]:
    """Build a deterministic read-only plan from current readiness state."""

    ctx = build_discover_context(root_path)
    blockers = _collect_blockers(ctx)
    actions = _derive_actions(ctx, blockers)
    status = _derive_plan_status(actions, blockers)
    payload = {
        "schema_version": "1",
        "projection_kind": "setup_plan",
        "recomputation": True,
        "root": str(ctx.root_path),
        "head_commit": ctx.head_commit,
        "status": status,
        "blockers": blockers,
        "actions": actions,
        "read_only": True,
    }
    payload["plan_id"] = _compute_plan_id(payload)
    return payload


def _collect_blockers(ctx: DiscoverContext) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    if ctx.config_error is not None:
        blockers.append(
            {
                "kind": "invalid_pyproject",
                "reason": str(ctx.config_error),
            }
        )
    config_path = ctx.root_path / "pyproject.toml"
    if not config_path.is_file():
        blockers.append(
            {
                "kind": "missing_pyproject",
                "reason": "pyproject.toml is required for tool.codeclone merges",
            }
        )
    return blockers


def _derive_actions(
    ctx: DiscoverContext,
    blockers: list[dict[str, object]],
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    pyproject_blocked = any(
        item["kind"] in {"invalid_pyproject", "missing_pyproject"} for item in blockers
    )
    if not pyproject_blocked:
        if not ctx.has_codeclone_section:
            _append_pyproject_action(
                actions,
                ctx,
                capability_id="analysis",
                updates={"baseline": DEFAULT_BASELINE_PATH},
            )
        elif not ctx.audit_enabled:
            _append_pyproject_action(
                actions,
                ctx,
                capability_id="audit_and_intents",
                updates={"audit_enabled": True},
            )

    gitignore_action = _plan_gitignore_append(ctx)
    if gitignore_action is not None:
        actions.append(gitignore_action)

    actions.sort(key=lambda item: str(item["id"]))
    return actions


def _append_pyproject_action(
    actions: list[dict[str, object]],
    ctx: DiscoverContext,
    *,
    capability_id: str,
    updates: dict[str, object],
) -> None:
    action = _plan_pyproject_merge(
        ctx,
        capability_id=capability_id,
        updates=updates,
    )
    if action is not None:
        actions.append(action)


def _plan_pyproject_merge(
    ctx: DiscoverContext,
    *,
    capability_id: str,
    updates: dict[str, object],
) -> dict[str, object] | None:
    action_id = f"pyproject_merge:{capability_id}"
    try:
        result = merge_tool_codeclone(ctx.root_path, updates, dry_run=True)
    except PyprojectWriterError as exc:
        return {
            "id": action_id,
            "capability_id": capability_id,
            "kind": "pyproject_merge",
            "path": "pyproject.toml",
            "status": "blocked",
            "block_reason": str(exc),
            "updates": {},
            "changed_keys": [],
            "created_section": False,
            "preview": {"unified_diff": ""},
        }

    if not result.changed_keys:
        return None

    before_text = _read_pyproject_text(ctx.root_path)
    preview_text = result.preview_text or ""
    return {
        "id": action_id,
        "capability_id": capability_id,
        "kind": "pyproject_merge",
        "path": "pyproject.toml",
        "status": "ready",
        "block_reason": "",
        "updates": {key: updates[key] for key in result.changed_keys},
        "changed_keys": list(result.changed_keys),
        "created_section": result.created_section,
        "preview": {
            "unified_diff": _unified_diff(
                before_text,
                preview_text,
                "pyproject.toml",
            ),
        },
    }


def _plan_gitignore_append(ctx: DiscoverContext) -> dict[str, object] | None:
    if ctx.gitignore_covers_cache:
        return None

    path = ctx.root_path / ".gitignore"
    before_text = ""
    if path.is_file():
        try:
            before_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {
                "id": "gitignore_append:workspace_hygiene",
                "capability_id": "workspace_hygiene",
                "kind": "gitignore_append",
                "path": ".gitignore",
                "status": "blocked",
                "block_reason": str(exc),
                "lines": [GITIGNORE_CODECLONE_CACHE_SUGGESTED_ENTRY],
                "preview": {"unified_diff": ""},
            }

    line = GITIGNORE_CODECLONE_CACHE_SUGGESTED_ENTRY
    after_text = append_gitignore_line(before_text, line)
    if before_text == after_text:
        return None

    return {
        "id": "gitignore_append:workspace_hygiene",
        "capability_id": "workspace_hygiene",
        "kind": "gitignore_append",
        "path": ".gitignore",
        "status": "ready",
        "block_reason": "",
        "lines": [line],
        "preview": {
            "unified_diff": _unified_diff(before_text, after_text, ".gitignore"),
        },
    }


def _derive_plan_status(
    actions: list[dict[str, object]],
    blockers: list[dict[str, object]],
) -> PlanStatus:
    ready_actions = [item for item in actions if item.get("status") == "ready"]
    if ready_actions:
        return "ready"
    blocked_actions = [item for item in actions if item.get("status") == "blocked"]
    if blockers or blocked_actions:
        return "blocked"
    return "empty"


def _compute_plan_id(payload: dict[str, object]) -> str:
    raw_actions = payload.get("actions", [])
    action_items: list[dict[str, object]] = []
    if isinstance(raw_actions, list):
        action_items = [item for item in raw_actions if isinstance(item, dict)]
    canonical = {
        "head_commit": payload.get("head_commit"),
        "root": payload.get("root"),
        "blockers": payload.get("blockers"),
        "actions": [
            {key: value for key, value in action.items() if key != "preview"}
            for action in action_items
        ],
    }
    digest_input = json_text(canonical, sort_keys=True, trailing_newline=False)
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]


def _read_pyproject_text(root_path: Path) -> str:
    config_path = root_path / "pyproject.toml"
    if not config_path.is_file():
        return ""
    with open_repo_config(root_path) as handle:
        return handle.read().decode("utf-8")


def _unified_diff(before_text: str, after_text: str, filename: str) -> str:
    before_lines = before_text.splitlines(keepends=True)
    after_lines = after_text.splitlines(keepends=True)
    if not before_lines and not after_text:
        return ""
    if not before_lines:
        before_lines = [""]
    diff_lines = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    )
    return "".join(f"{item}\n" for item in diff_lines)


__all__ = ["build_setup_plan"]
