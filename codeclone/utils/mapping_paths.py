# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Address nested sub-mappings by dotted path.

Every renderer opens by projecting the same report document into the handful of
sections it needs, and each projection was written as its own
``as_mapping(parent.get(key))`` statement. In the markdown and text renderers
that prologue ran to roughly twenty-five near-identical lines apiece, and the
audit analysis.completed builder repeated the same shape; the clone lanes
reported both as duplicated projection scaffolding.

:func:`sections` collapses a whole prologue into one call. Paths are resolved
key by key, so a nested section is addressed directly (``"integrity.digests.
envelope"``) instead of through intermediate locals, and the renderer keeps a
flat, explicitly ordered list of what it reads from the document.

This lives in utils (ring r1) rather than beside one consumer so that both the
r4 renderers and the r2p audit builder can reach it without a ring violation.

Resolution is deliberately tolerant, matching the behaviour the callers
already relied on: a missing key, a null, or a non-mapping value at any step
yields an empty mapping rather than raising, so a partial document still
renders.
"""

from __future__ import annotations

from collections.abc import Mapping

from .coerce import as_mapping


def section(source: Mapping[str, object], path: str) -> Mapping[str, object]:
    """Return the sub-mapping addressed by one dotted path."""

    current = source
    for key in path.split("."):
        current = as_mapping(current.get(key))
    return current


def sections(
    source: Mapping[str, object],
    *paths: str,
) -> tuple[Mapping[str, object], ...]:
    """Return the sub-mappings addressed by dotted paths, in the given order."""

    return tuple(section(source, path) for path in paths)


__all__ = ["section", "sections"]
