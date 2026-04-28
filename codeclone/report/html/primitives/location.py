# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared location/path helpers for HTML section renderers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .._context import ReportContext


def relative_location_path(ctx: ReportContext, item: Mapping[str, object]) -> str:
    relative_path = str(item.get("relative_path", "")).strip()
    if relative_path:
        return relative_path
    filepath = str(item.get("filepath", "")).strip()
    if not filepath:
        return ""
    return ctx.relative_path(filepath).strip()


def location_file_target(
    ctx: ReportContext,
    item: Mapping[str, object],
    *,
    relative_path: str,
) -> str:
    filepath = str(item.get("filepath", "")).strip()
    if filepath:
        path_obj = Path(filepath)
        if path_obj.is_absolute():
            return filepath
        if ctx.scan_root:
            return str((Path(ctx.scan_root) / path_obj).resolve())
        return filepath
    if ctx.scan_root and relative_path:
        return str((Path(ctx.scan_root) / relative_path).resolve())
    return relative_path


__all__ = ["location_file_target", "relative_location_path"]
