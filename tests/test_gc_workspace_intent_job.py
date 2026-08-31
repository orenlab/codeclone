# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The workspace-intent collector under the unified GC protocol.

The maintainer's reality check for this surface, in this surface's own
ring: the registry cleanup that already lived in the tree becomes a job of
the unified orchestrator, wrapping the REAL ``lazy_close_eligible_records``
— no protocol bending, and the reason words are the ones this surface's
own terminal-status decider already speaks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from codeclone.api.gc import (
    GC_COLLECT_CORRUPT,
    GC_COLLECT_EXPIRED,
    GC_COLLECT_ORPHANED,
    GC_COLLECT_REASONS,
    GC_HOLD_OWNER_ALIVE,
    GcJobReport,
    run_gc,
)
from codeclone.surfaces.mcp._workspace_intent_lifecycle import gc_status_for_reason
from codeclone.surfaces.mcp._workspace_intent_store import (
    get_workspace_intent_store,
    lazy_close_eligible_records,
)
from tests.test_workspace_intents import _record


def test_the_intent_terminal_status_speaks_the_closed_collect_vocabulary() -> None:
    """The words reach the deciders: the intent store's own terminal-status
    decider maps its removal reasons onto exactly the two collect reasons
    the unified vocabulary adopted from it."""
    assert gc_status_for_reason("orphaned") == GC_COLLECT_ORPHANED
    assert gc_status_for_reason("ttl_expired") == GC_COLLECT_EXPIRED
    assert gc_status_for_reason("lease_expired") == GC_COLLECT_EXPIRED
    assert {GC_COLLECT_ORPHANED, GC_COLLECT_EXPIRED} <= GC_COLLECT_REASONS


@dataclass
class _WorkspaceIntentGcJob:
    """The workspace-intent registry as a job, wrapping the REAL cleanup.

    Collection on this surface is removal from the live coordination
    universe — the file backend unlinks the record, the SQLite backend
    transitions it to a terminal status kept as history.  Either way it is
    the job's own storage semantics, unchanged by the protocol.  The
    reason mapping is exactly ``gc_status_for_reason``'s split: ``orphaned``
    maps to orphaned, every expiry-class reason to expired.
    """

    store: object
    name: str = field(default="workspace_intents", init=False)

    def collect(self) -> GcJobReport:
        candidates = len(self.store.list_records_raw())  # type: ignore[attr-defined]
        result = lazy_close_eligible_records(self.store)  # type: ignore[arg-type]
        collected: dict[str, int] = {}
        for reason in result.closed_reasons.values():
            key = GC_COLLECT_ORPHANED if reason == "orphaned" else GC_COLLECT_EXPIRED
            collected[key] = collected.get(key, 0) + 1
        if result.corrupted_removed:
            collected[GC_COLLECT_CORRUPT] = len(result.corrupted_removed)
        return GcJobReport.build(
            job=self.name,
            candidates=candidates + len(result.corrupted_removed),
            held={GC_HOLD_OWNER_ALIVE: candidates - len(result.closed_ids)},
            collected=collected,
        )


def test_the_intent_collector_fits_the_protocol_without_bending(
    tmp_path: Path,
) -> None:
    """One live-owner record held, one lease-expired record collected, the
    real registry doing the real removal — dispatched by the unified
    orchestrator with honest per-reason accounting."""
    intent_store = get_workspace_intent_store(tmp_path)
    assert intent_store.write(_record(intent_id="intent-alive-001"))
    assert intent_store.write(
        _record(
            intent_id="intent-stale-002",
            start_epoch=101,
            expires_delta=timedelta(hours=-2),
        )
    )

    receipt = run_gc([_WorkspaceIntentGcJob(store=intent_store)])

    assert len(receipt.reports) == 1
    report = receipt.reports[0]
    assert report.job == "workspace_intents"
    assert report.candidates == 2
    assert report.held_count(GC_HOLD_OWNER_ALIVE) == 1
    assert report.collected_count(GC_COLLECT_EXPIRED) == 1
    assert report.refusal is None

    remaining = {
        record.intent_id: record.status
        for record in get_workspace_intent_store(tmp_path).list_records_raw()
    }
    assert "intent-stale-002" not in remaining
    assert remaining["intent-alive-001"] == "active"
