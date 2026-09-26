# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Read-only setup plan projection (pyproject and gitignore previews)."""

from __future__ import annotations

import difflib
import hashlib
import uuid
from pathlib import Path
from typing import Final, Literal, TypeGuard

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

#: Prefix of the uuid5 name a planned ``baseline_scope_id`` is derived from; it
#: keeps these ids apart from any other id derived under ``NAMESPACE_URL``.
_SCOPE_ID_NAME_PREFIX: Final = "urn:codeclone:setup:baseline-scope-id:"


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
        _append_pyproject_action(
            actions,
            ctx,
            capability_id="analysis",
            updates=_analysis_updates(ctx),
        )
        _append_pyproject_action(
            actions,
            ctx,
            capability_id="audit_and_intents",
            updates=_audit_updates(ctx),
        )

    gitignore_action = _plan_gitignore_append(ctx)
    if gitignore_action is not None:
        actions.append(gitignore_action)

    actions.sort(key=lambda item: str(item["id"]))
    return actions


def _analysis_updates(ctx: DiscoverContext) -> dict[str, object]:
    """What ``[tool.codeclone]`` still lacks for analysis and its baseline.

    A missing section gets the default baseline path, spelled relative: the
    file is committed, and every checkout and CI resolves it against its own
    root. A missing ``baseline_scope_id`` is proposed whether or not the section
    exists, because ``--update-baseline`` refuses without it -- a setup that
    stopped short of the key would leave the project unable to create the
    baseline it had just configured. A key that is present is never proposed
    again: it is the identity every recorded baseline was bound to.
    """

    updates: dict[str, object] = {}
    if not ctx.has_codeclone_section:
        updates["baseline"] = DEFAULT_BASELINE_PATH
    if ctx.config.get("baseline_scope_id") is None:
        updates["baseline_scope_id"] = _planned_scope_id(ctx)
    return updates


def _audit_updates(ctx: DiscoverContext) -> dict[str, object]:
    """``audit_enabled`` for a section that exists but leaves the trail off."""

    if ctx.has_codeclone_section and not ctx.audit_enabled:
        return {"audit_enabled": True}
    return {}


def _planned_scope_id(ctx: DiscoverContext) -> str:
    """The ``baseline_scope_id`` this plan proposes, derived from the plan's inputs.

    Not a fresh ``uuid4`` per call. The plan is a deterministic projection and
    its ``plan_id`` digests the proposed values; ``setup apply`` recomputes the
    plan instead of receiving it, in another process when the operator ran
    ``setup plan`` first. A random value would make every recomputation another
    plan: the id shown in the preview would never be the id written, and
    ``--plan-id`` would refuse every apply as stale.

    Not name-derived either. The key tells this project's baseline from a
    stranger's, and an id computed from a project name would hand every
    same-named project the same one. The inputs are the resolved absolute root,
    the ``HEAD`` commit and the exact ``pyproject.toml`` text, so two projects
    receive one id only when they share all three -- for a git checkout, the
    same commit history at the same path.
    """

    pyproject_text = _read_pyproject_text(ctx.root_path)
    identity = json_text(
        {
            "head_commit": ctx.head_commit,
            "pyproject_sha256": hashlib.sha256(
                pyproject_text.encode("utf-8")
            ).hexdigest(),
            "root": str(ctx.root_path),
        },
        sort_keys=True,
        trailing_newline=False,
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, _SCOPE_ID_NAME_PREFIX + identity))


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
        action_items = [item for item in raw_actions if _is_action_item(item)]
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


def _is_action_item(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


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
