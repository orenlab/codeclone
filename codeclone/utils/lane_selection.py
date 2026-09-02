# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""One owner for "does this run collect the api-surface lane".

The answer was derived in six places from four different expressions. The
worker gate asked ``not skip_metrics and api_surface``; the cache profile key
asked ``bool(api_surface)``; the lane contract asked
``collect_metrics and api_surface``; one cache site answered a hardcoded
``True``; the presentation layer asked ``args.api_surface``. Measured, that let
one run write cache rows whose key claimed a lane the extraction never filled,
and report ``enabled: false`` beside an armed ``fail_on_api_break`` inside one
document.

The predicate lives in ring 1 because both halves of the split need it: the
pipeline (ring 2) decides what to materialize, and the CLI and MCP surfaces
(ring 4) key the cache before a bootstrap object exists. A ring-2 home would be
reachable from only one of them, which is how the copies started.

It reads the arguments defensively because the two surfaces build their
namespaces separately and a missing attribute must mean "off", never a crash on
a surface that never grew the flag.
"""

from __future__ import annotations

__all__ = ["api_surface_collection_enabled"]


def api_surface_collection_enabled(args: object) -> bool:
    """Whether ``args`` asks for the api-surface lane to be collected.

    ``skip_metrics`` wins: the api surface is a metric family, and a run that
    skips metrics runs no per-file api extraction whatever the flag says. That
    subordination is the fact the cache profile key was missing, so it belongs
    here rather than at each call site.
    """

    if bool(getattr(args, "skip_metrics", False)):
        return False
    return bool(getattr(args, "api_surface", False))
