# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E2 (2026-09-26): an MCP-published run carries its
comparison facts as store rows.

The pin reads the published store the way census-3 probe F did — the
distinct families of the run's membership — so it is spelled without any
name the wave introduces and runs unchanged on a tree that has none of it.
The expected names are an INDEPENDENT literal (the grammar-pin precedent):
asking the store table which families it declares would prove only that the
table was read twice.

The serving corpus runs WITHOUT a baseline, and that is the point: "no
baseline" is itself a comparison statement — the witness says ``missing``,
every lane says why it cannot be compared, and the clone pair the corpus
carries is annotated ``unavailable`` — never silence.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

from tests._served_run import ServedRunStoreProjection

#: The comparison families a baseline-less MCP run must publish: the two
#: baseline witnesses, per-lane trust, per-lane availability, the disabled
#: capabilities, and the novelty of the one governed finding population the
#: serving corpus carries (a function clone pair).
_PUBLISHED_WITHOUT_A_BASELINE = frozenset(
    {
        "baseline_witness",
        "clone_novelty",
        "comparison_availability",
        "disabled_capability",
        "lane_trust",
        "metrics_baseline_witness",
    }
)


def _published_families(served: ServedRunStoreProjection) -> set[str]:
    uri = f"file:{served.store_path}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT f.family FROM run_members m "
                "JOIN objects o ON o.object_pk = m.object_pk "
                "JOIN families f ON f.family_pk = o.family_pk "
                "JOIN runs r ON r.run_pk = m.run_pk WHERE r.run_id = ?",
                (served.store_run_id,),
            )
        }


def test_the_comparison_families_are_published_as_store_rows(
    served_run_store_projection: ServedRunStoreProjection,
) -> None:
    families = _published_families(served_run_store_projection)
    # The instrument is on: the run's analysis families are there.
    assert {"clone_group", "run_scalar", "analysis_population"} <= families
    missing = sorted(_PUBLISHED_WITHOUT_A_BASELINE - families)
    assert not missing, f"comparison families absent from the published run: {missing}"
