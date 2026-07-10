# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Compatibility exports for surface-neutral workspace intent paths."""

from __future__ import annotations

from pathlib import Path

from ...utils.json_io import read_json_object
from ...workspace_intent.paths import (
    REGISTRY_DIR_PARTS,
    intent_filename,
    intent_path,
    is_safe_intent_id,
    is_safe_intent_path,
    record_sort_key,
    registry_dir,
    registry_files,
    unlink,
)
from ...workspace_intent.paths import (
    read_payload as _read_payload,
)
from ...workspace_intent.paths import (
    safe_remove_own_intent as _safe_remove_own_intent,
)


def read_payload(path: Path) -> dict[str, object] | None:
    return _read_payload(path, reader=read_json_object)


def safe_remove_own_intent(
    *,
    root: Path,
    pid: int,
    start_epoch: int,
    intent_id: str,
) -> bool:
    return _safe_remove_own_intent(
        root=root,
        pid=pid,
        start_epoch=start_epoch,
        intent_id=intent_id,
        safety_check=is_safe_intent_path,
    )


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
