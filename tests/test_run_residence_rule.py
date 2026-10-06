# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one payload drop rule, row by row of its decision table.

A held run's payload may go only while the run store can stand in for it;
each row below names the one input that keeps it, and the store's proof is
asked last -- only when nothing else kept the payload.  The session's side
of the rule, on a real store, is held in ``test_mcp_run_payload``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from codeclone.api.intent_run_lease import RunLeaseState
from codeclone.api.run_residence import payload_droppable
from codeclone.models import RunSnapshotLink

_STORE_RUN = "s" * 64
_REPORT = "r" * 64
_SCOPE = "c" * 64


# ── the drop rule ────────────────────────────────────────────────────────


def _link(state: str = "linked", store_run_id: str = _STORE_RUN) -> RunSnapshotLink:
    stated = state in {"linked", "unrecorded"}
    return RunSnapshotLink(
        state=state,
        outcome="published" if state == "linked" else "disabled",
        store_run_id=store_run_id if stated else "",
        analysis_scope_digest=_SCOPE if stated else "",
        report_run_identity=_REPORT if stated else "",
        refusal="store_unavailable" if state == "unrecorded" else "",
    )


def _lease(*, held: bool = True, store_run_id: str = _STORE_RUN) -> RunLeaseState:
    return RunLeaseState(
        held=held,
        reason="held" if held else "lease_refused",
        lease_id="intent:1:2:3:intent-x",
        ttl_seconds=60,
        store_run_id=store_run_id,
        expires_at=1 if held else None,
    )


@dataclass
class _Proof:
    answer: bool = True
    asked: int = 0

    def __call__(self) -> bool:
        self.asked += 1
        return self.answer


_ROWS: dict[str, tuple[dict[str, object], bool, bool]] = {
    # row: (inputs, verdict, the proof was asked)
    "published, unpinned, proven": ({}, True, True),
    "pinned, every lease held": (
        {"pins": 2, "leases": (_lease(), _lease())},
        True,
        True,
    ),
    "no link": ({"link": None}, False, False),
    "unpublished": ({"link": _link("unpublished")}, False, False),
    "unrecorded": ({"link": _link("unrecorded")}, False, False),
    "switch names memory": ({"store_serves": False}, False, False),
    "a pin no lease accounts for": ({"pins": 1, "leases": ()}, False, False),
    "an intent without a lease": ({"pins": 1, "leases": (None,)}, False, False),
    "a lease not held": (
        {"pins": 2, "leases": (_lease(), _lease(held=False))},
        False,
        False,
    ),
    "a lease on another run": (
        {"pins": 1, "leases": (_lease(store_run_id="o" * 64),)},
        False,
        False,
    ),
    "membership not proven": ({"proof": False}, False, True),
}


@pytest.mark.parametrize("row", sorted(_ROWS))
def test_the_drop_rule_row_by_row(row: str) -> None:
    inputs, verdict, asked = _ROWS[row]
    proof = _Proof(answer=bool(inputs.get("proof", True)))
    leases = inputs.get("leases", ())
    assert isinstance(leases, tuple)

    decided = payload_droppable(
        link=inputs["link"] if "link" in inputs else _link(),  # type: ignore[arg-type]
        store_serves=bool(inputs.get("store_serves", True)),
        pins=int(str(inputs.get("pins", 0))),
        leases=leases,
        membership_proven=proof,
    )

    assert decided is verdict
    # The store is asked last, and only when nothing else kept the payload.
    assert proof.asked == (1 if asked else 0)
