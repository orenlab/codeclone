# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Unified data-attribute builder for HTML elements."""

from __future__ import annotations

from .escape import _escape_html

__all__ = ["_build_data_attrs"]


def _build_data_attrs(attrs: dict[str, object | None]) -> str:
    """Build a space-prefixed HTML data-attribute string from a dict.

    None values are omitted; empty strings are preserved as ``attr=""``.
    All values are escaped.
    Returns ``''`` when no attrs survive, or ``' data-foo="bar" ...'``
    (leading space) otherwise.
    """
    parts: list[str] = []
    for key, val in attrs.items():
        if val is None:
            continue
        s = str(val)
        parts.append(f'{key}="{_escape_html(s)}"')
    return f" {' '.join(parts)}" if parts else ""
