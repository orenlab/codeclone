# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E3 (2026-09-27): an MCP-published run carries its
evaluation facts as store rows.

The pin reads the published store the way the E2 publication pin does — the
distinct families of the run's membership — so it is spelled without any
name the wave introduces and runs unchanged on a tree that has none of it.
The expected names are an INDEPENDENT literal: asking the store which
families it declares would prove only that the table was read twice.

The serving corpus runs without a baseline and without a gate: the run is
still evaluated — under the request it was analysed with (every gate off),
with a health verdict, a band per measured unit, a verdict per finding and
the document's selections — and none of that may be silence.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

from tests._served_run import ServedRunStoreProjection

#: The evaluation families a baseline-less, gate-less MCP run must publish.
_PUBLISHED_WITHOUT_A_GATE = frozenset(
    {
        "evaluation_contract",
        "evaluation_request",
        "finding_evaluation",
        "gate_outcome",
        "health_result",
        "hotlist_selection",
        "unit_risk_result",
    }
)


def _published_families(served: ServedRunStoreProjection) -> set[str]:
    uri = f"file:{served.store_path}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT o.family FROM run_members m "
                "JOIN objects o ON o.object_pk = m.object_pk "
                "JOIN runs r ON r.run_pk = m.run_pk WHERE r.run_id = ?",
                (served.store_run_id,),
            )
        }


def test_the_evaluation_families_are_published_as_store_rows(
    served_run_store_projection: ServedRunStoreProjection,
) -> None:
    families = _published_families(served_run_store_projection)
    # The instrument is on: the run's analysis and comparison families are there.
    assert {"clone_group", "run_scalar", "baseline_witness"} <= families
    missing = sorted(_PUBLISHED_WITHOUT_A_GATE - families)
    assert not missing, f"evaluation families absent from the published run: {missing}"
