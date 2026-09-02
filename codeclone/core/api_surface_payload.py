# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence

from ..metrics.api_population import visible_api_surface
from ..models import ApiBreakingChange, ApiSurfaceSnapshot
from ..utils.coerce import as_int, as_str


def _api_surface_summary(api_surface: ApiSurfaceSnapshot | None) -> dict[str, object]:
    # The family is the API, not the collection: the run keeps every collected
    # symbol because that is what the lane stores, and reports the visible
    # projection of it -- the symbols a public namespace provably or possibly
    # binds. ``enabled`` is about the lane, so it reads the collection.
    visible = visible_api_surface(api_surface)
    modules = visible.modules if visible is not None else ()
    return {
        "enabled": api_surface is not None,
        "modules": len(modules),
        "public_symbols": sum(len(module.symbols) for module in modules),
        "added": 0,
        "breaking": 0,
        "strict_types": False,
    }


def _api_surface_rows(
    api_surface: ApiSurfaceSnapshot | None,
) -> list[dict[str, object]]:
    visible = visible_api_surface(api_surface)
    if visible is None:
        return []
    rows: list[dict[str, object]] = []
    for module in visible.modules:
        rows.extend(
            {
                "record_kind": "symbol",
                "module": module.module,
                "filepath": module.filepath,
                "qualname": symbol.qualname,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
                "symbol_kind": symbol.kind,
                "exported_via": symbol.exported_via,
                "params_total": len(symbol.params),
                "params": [
                    {
                        "name": param.name,
                        "kind": param.kind,
                        "has_default": param.has_default,
                        "annotated": bool(param.annotation_hash),
                    }
                    for param in symbol.params
                ],
                "returns_annotated": bool(symbol.returns_hash),
            }
            for symbol in module.symbols
        )
    return sorted(
        rows,
        key=lambda item: (
            as_str(item.get("filepath")),
            as_int(item.get("start_line")),
            as_int(item.get("end_line")),
            as_str(item.get("qualname")),
            as_str(item.get("record_kind")),
        ),
    )


def _breaking_api_surface_rows(changes: Sequence[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for change in changes:
        if not isinstance(change, ApiBreakingChange):
            continue
        module_name, _, _local_name = change.qualname.partition(":")
        rows.append(
            {
                "record_kind": "breaking_change",
                "module": module_name,
                "filepath": change.filepath,
                "qualname": change.qualname,
                "start_line": change.start_line,
                "end_line": change.end_line,
                "symbol_kind": change.symbol_kind,
                "change_kind": change.change_kind,
                "detail": change.detail,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            as_str(item.get("filepath")),
            as_int(item.get("start_line")),
            as_int(item.get("end_line")),
            as_str(item.get("qualname")),
            as_str(item.get("change_kind")),
        ),
    )
