# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The three off-report slices an MCP execution serves, as a transport value.

``MCPRunRecord`` lives in ring ``r4``; the canonical run store it is compared
against lives in ring ``r2``.  A test module that imported both would be an
``r4`` subject and every ``r2`` import in it a new architecture-ratchet entry
(the Phase 39S test-import law), so the ``r4`` half of that comparison is
driven from ``tests/conftest.py`` — exactly as ``run_store_cli`` is — and
hands the consumer this value instead of the record itself.

Two of the three slices keep their own types: the surface serves
``processing_result.function_relationship_facts`` and
``processing_result.module_deps`` verbatim, and both are ``r2`` values.  The
unit index is the one projection the surface builds for itself, so it is
copied field for field into :class:`ServedUnitLocation` rather than
re-derived here — a second derivation would be a second dialect of one fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codeclone.models import FunctionRelationshipFacts, ModuleDep


@dataclass(frozen=True, slots=True)
class ServedUnitLocation:
    """One row of the served unit index, copied field for field."""

    qualname: str
    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedRunStoreProjection:
    """What one MCP execution serves from RAM, beside the run it published.

    ``store_run_id`` names the canonical row that same execution wrote, so
    the two sides of every comparison are one run — not one run and a
    look-alike over the same tree.
    """

    root: Path
    store_path: Path
    store_run_id: str
    unit_inventory: tuple[ServedUnitLocation, ...]
    relationship_facts: tuple[FunctionRelationshipFacts, ...]
    module_imports: tuple[ModuleDep, ...]
