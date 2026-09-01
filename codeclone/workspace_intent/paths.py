# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Final

from ..paths.workspace import REGISTRY_DIR_PARTS
from ..utils.json_io import read_json_object
from .contract import WorkspaceIntentRecord

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
    """Every safe intent file in the registry, one entry per resolved target.

    Identity here is the resolved target, never the spelling that reached it.
    This is the single door every registry consumer reads through, so it is
    also the only place two names for one record can be collapsed. Keyed by
    spelling instead, one held scope is announced twice in
    ``concurrent_intents``, and the removal path -- which unlinks the one path
    it recorded per intent id -- leaves the other name behind. Where several
    spellings share a target the one that *is* its target wins, so removing an
    intent removes the record rather than a link to it.
    """

    directory = registry_dir(root)
    chosen: dict[Path, Path] = {}
    try:
        for path in sorted(directory.glob("*.json")):
            if not is_safe_intent_path(path, directory):
                continue
            # Safe to resolve unguarded: the predicate above resolved this same
            # path a moment ago. A second try/except here would be a branch no
            # input can reach, which is worse than the OSError it imagines.
            target = path.resolve(strict=False)
            current = chosen.get(target)
            if current is None or (current != target and path == target):
                chosen[target] = path
    except OSError:
        return ()
    return tuple(sorted(chosen.values()))


def read_payload(
    path: Path,
    *,
    reader: Callable[[Path], dict[str, object]] = read_json_object,
) -> dict[str, object] | None:
    try:
        return reader(path)
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
    """Whether ``expected`` may be read or removed as a registry intent file.

    The property is resolved containment -- ``resolve(candidate)`` lands inside
    ``resolve(registry)`` -- and deliberately not ``candidate ==
    resolve(candidate)``. Demanding an already-resolved spelling refuses a link
    whose target is a legitimate record inside the registry, and buys nothing
    for it: the substitution equality was reaching for is caught one line down,
    on the resolved target, which is the one thing no spelling can disguise.

    The cost of over-refusing is not symmetric across the two consumers, which
    is why it is a security bug rather than an inconvenience. The edit gate
    fails closed and merely stops its own agent. Conflict detection fails OPEN:
    an invisible record is no record, so ``start_controlled_change`` hands out
    an active intent on scope another live agent is holding.
    """

    try:
        if not expected.is_absolute():
            return False
        resolved = expected.resolve(strict=False)
        resolved_registry = registry.resolve(strict=False)
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
    safety_check: Callable[[Path, Path], bool] = is_safe_intent_path,
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
        if not safety_check(expected, registry):
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
