# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Minimal R3 door over the canonical R2 source-population owner.

The MCP drift projection (r4) must derive "the current population" by the
same rule the analysis did, and it may not import ``codeclone.paths``
directly: r4 reaches r2 only through this ring. The door re-exports the owner
unchanged -- the population is already a frozen carrier, there is nothing to
project -- so the derivation rule keeps one spelling.
"""

from __future__ import annotations

from ..paths.population import derive_source_population

__all__ = ["derive_source_population"]
