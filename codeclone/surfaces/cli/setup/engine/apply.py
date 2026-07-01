# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Bounded setup apply engine for plan actions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from .....config.pyproject_writer import PyprojectWriterError, merge_tool_codeclone
from .....paths.gitignore import (
    append_gitignore_line,
    repo_gitignore_covers_codeclone_cache,
    write_gitignore_text_atomically,
)
from .plan import build_setup_plan

ApplyStatus = Literal["noop", "preview", "applied", "partial", "failed", "blocked"]
ActionApplyStatus = Literal["applied", "preview", "skipped", "failed"]


def apply_setup_plan(root_path: Path, *, dry_run: bool = False) -> dict[str, object]:
    """Recompute the current plan and apply ready actions in sorted order."""

    plan = build_setup_plan(root_path)
    ready_actions = _ready_actions(plan)
    if not ready_actions:
        return _build_apply_result(
            plan,
            status=_noop_or_blocked_status(plan),
            dry_run=dry_run,
            results=(),
        )

    results: list[dict[str, object]] = []
    for action in ready_actions:
        result = _apply_action(root_path, action, dry_run=dry_run)
        results.append(result)
        if result["status"] == "failed":
            status: ApplyStatus = "partial" if _any_applied(results) else "failed"
            if dry_run:
                status = "preview"
            return _build_apply_result(
                plan,
                status=status,
                dry_run=dry_run,
                results=tuple(results),
            )

    status = "preview" if dry_run else "applied"
    return _build_apply_result(
        plan,
        status=status,
        dry_run=dry_run,
        results=tuple(results),
    )


def _ready_actions(plan: Mapping[str, object]) -> list[dict[str, object]]:
    raw = plan.get("actions")
    if not isinstance(raw, list):
        return []
    ready = [
        item for item in raw if isinstance(item, dict) and item.get("status") == "ready"
    ]
    ready.sort(key=lambda item: str(item.get("id", "")))
    return ready


def _noop_or_blocked_status(plan: Mapping[str, object]) -> ApplyStatus:
    if plan.get("status") == "blocked":
        return "blocked"
    return "noop"


def _build_apply_result(
    plan: Mapping[str, object],
    *,
    status: ApplyStatus,
    dry_run: bool,
    results: tuple[dict[str, object], ...],
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "projection_kind": "setup_apply",
        "recomputation": True,
        "root": plan.get("root"),
        "head_commit": plan.get("head_commit"),
        "plan_id": plan.get("plan_id"),
        "plan_status": plan.get("status"),
        "status": status,
        "dry_run": dry_run,
        "results": list(results),
    }


def _apply_action(
    root_path: Path,
    action: Mapping[str, object],
    *,
    dry_run: bool,
) -> dict[str, object]:
    action_id = str(action.get("id", ""))
    kind = str(action.get("kind", ""))
    handler = _ACTION_HANDLERS.get(kind)
    if handler is None:
        return {
            "id": action_id,
            "kind": kind,
            "path": action.get("path", ""),
            "status": "failed",
            "message": f"Unsupported plan action kind: {kind}",
        }
    return handler(root_path, action, dry_run)


def _apply_pyproject_merge(
    root_path: Path,
    action: Mapping[str, object],
    dry_run: bool,
) -> dict[str, object]:
    action_id = str(action.get("id", ""))
    updates_raw = action.get("updates")
    if not isinstance(updates_raw, dict):
        return _failed_result(
            action_id,
            "pyproject_merge",
            "pyproject.toml",
            "missing updates",
        )

    updates = {str(key): value for key, value in updates_raw.items()}
    try:
        result = merge_tool_codeclone(root_path, updates, dry_run=dry_run)
    except PyprojectWriterError as exc:
        return _failed_result(action_id, "pyproject_merge", "pyproject.toml", str(exc))

    if not result.changed_keys:
        return {
            "id": action_id,
            "kind": "pyproject_merge",
            "path": "pyproject.toml",
            "status": "skipped",
            "message": "already satisfied",
            "changed_keys": [],
        }

    status: ActionApplyStatus = "preview" if dry_run else "applied"
    return {
        "id": action_id,
        "kind": "pyproject_merge",
        "path": "pyproject.toml",
        "status": status,
        "message": "",
        "changed_keys": list(result.changed_keys),
        "created_section": result.created_section,
    }


def _apply_gitignore_append(
    root_path: Path,
    action: Mapping[str, object],
    dry_run: bool,
) -> dict[str, object]:
    action_id = str(action.get("id", ""))
    lines_raw = action.get("lines")
    if not isinstance(lines_raw, list) or not lines_raw:
        return _failed_result(
            action_id,
            "gitignore_append",
            ".gitignore",
            "missing lines",
        )

    line = str(lines_raw[0])
    gitignore_path = root_path / ".gitignore"
    before_text = ""
    if gitignore_path.is_file():
        try:
            before_text = gitignore_path.read_text(encoding="utf-8")
        except OSError as exc:
            return _failed_result(action_id, "gitignore_append", ".gitignore", str(exc))

    after_text = append_gitignore_line(before_text, line)
    if before_text == after_text:
        return {
            "id": action_id,
            "kind": "gitignore_append",
            "path": ".gitignore",
            "status": "skipped",
            "message": "already satisfied",
            "lines": [line],
        }

    if not dry_run:
        try:
            write_gitignore_text_atomically(gitignore_path, after_text)
        except OSError as exc:
            return _failed_result(action_id, "gitignore_append", ".gitignore", str(exc))
        if not repo_gitignore_covers_codeclone_cache(root_path):
            return _failed_result(
                action_id,
                "gitignore_append",
                ".gitignore",
                "post-write verification failed",
            )

    status: ActionApplyStatus = "preview" if dry_run else "applied"
    return {
        "id": action_id,
        "kind": "gitignore_append",
        "path": ".gitignore",
        "status": status,
        "message": "",
        "lines": [line],
    }


def _failed_result(
    action_id: str,
    kind: str,
    path: str,
    message: str,
) -> dict[str, object]:
    return {
        "id": action_id,
        "kind": kind,
        "path": path,
        "status": "failed",
        "message": message,
    }


def _any_applied(results: list[dict[str, object]]) -> bool:
    return any(item.get("status") in {"applied", "preview"} for item in results)


_ACTION_HANDLERS: dict[
    str,
    Callable[[Path, Mapping[str, object], bool], dict[str, object]],
] = {
    "pyproject_merge": _apply_pyproject_merge,
    "gitignore_append": _apply_gitignore_append,
}


__all__ = ["apply_setup_plan"]
