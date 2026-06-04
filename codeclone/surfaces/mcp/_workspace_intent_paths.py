# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from ...paths.workspace import REGISTRY_DIR_PARTS
from ...utils.json_io import read_json_object
from ._workspace_intent_contract import WorkspaceIntentRecord

_SAFE_INTENT_ID_RE: Final = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


def registry_dir(root: Path) -> Path:
    return root.joinpath(*REGISTRY_DIR_PARTS)


def intent_filename(*, pid: int, start_epoch: int, intent_id: str) -> str:
    return f"{pid}-{start_epoch}-{intent_id}.json"


def intent_path(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
) -> Path:
    return registry_dir(root) / intent_filename(
        pid=pid,
        start_epoch=start_epoch,
        intent_id=intent_id,
    )


def registry_files(root: Path) -> tuple[Path, ...]:
    directory = registry_dir(root)
    try:
        return tuple(
            path
            for path in sorted(directory.glob("*.json"))
            if is_safe_intent_path(path, directory)
        )
    except OSError:
        return ()


def read_payload(path: Path) -> dict[str, object] | None:
    try:
        return read_json_object(path)
    except (OSError, TypeError, ValueError):
        return None


def unlink(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def record_sort_key(record: WorkspaceIntentRecord) -> tuple[str, int, str]:
    return (record.declared_at_utc, record.agent_pid, record.intent_id)


def is_safe_intent_id(value: object) -> bool:
    return isinstance(value, str) and _SAFE_INTENT_ID_RE.match(value) is not None


def is_safe_intent_path(expected: Path, registry: Path) -> bool:
    try:
        if not expected.is_absolute():
            return False
        resolved = expected.resolve(strict=False)
        resolved_registry = registry.resolve(strict=False)
        if resolved != expected:
            return False
        if not resolved.is_relative_to(resolved_registry):
            return False
        name = expected.name
        if not name.endswith(".json") or name.count("-") < 2:
            return False
        if expected.exists() and not expected.is_file():
            return False
    except (OSError, ValueError):
        return False
    return True


def safe_remove_own_intent(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
) -> bool:
    try:
        if not root.is_absolute():
            return False
        registry = registry_dir(root)
        expected = intent_path(
            root=root,
            pid=pid,
            start_epoch=start_epoch,
            intent_id=intent_id,
        )
        if not is_safe_intent_path(expected, registry):
            return False
        expected.unlink(missing_ok=True)
    except Exception:
        return False
    return True


__all__ = [
    "REGISTRY_DIR_PARTS",
    "intent_filename",
    "intent_path",
    "is_safe_intent_id",
    "is_safe_intent_path",
    "read_payload",
    "record_sort_key",
    "registry_dir",
    "registry_files",
    "safe_remove_own_intent",
    "unlink",
]
