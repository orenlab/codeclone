# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What a served answer is built from: the run store's facts, or the memory's.

The rollout contract (ruling 2026-09-05): ``store default OFF -> shadow read
with equivalence -> store-backed serving -> default ON``.  This module is
the shadow read and the store-backed serving in one decision, and every
branch of it is a counter:

* the record names a store run — its own publication, or the store's
  persisted index answering its report identity (the identity bridge, the
  road every process but the publisher takes) — the store answered, and the
  answer AGREES with what the record still holds in memory — the store's
  slices are served (``run_store_serving_store_backed``);
* the store answered and DISAGREES — memory is served and the divergence is
  counted (``run_store_serving_divergent``); the store never wins an
  argument with the producer's own answer, and a rollout is real only while
  this counter reads zero;
* the store could not answer for a reason the door names — memory is served
  and the fallback is counted (``run_store_serving_fallback``);
* nothing was published, or the rollout is off — memory by design
  (``run_store_serving_memory``).

The comparison is exact and order-sensitive over every field the surface
holds, while it still holds them: through the T2 rollout the record keeps
its slices, so the shadow read costs one bounded store read and one tuple
comparison per query, and buys a runtime witness that the store-backed
answer is the producer's answer.

Two readings go through that one decision (:func:`_shadow_read`), each with
its own memory side and its own agreement: the three slices of
``search_graph`` / ``get_implementation_context``, and the authority
candidate rows ``check_authority(section="candidates")`` pages.  The
candidates' memory is the sealed document's own rows, and their agreement
is the WIRE: a page serializes each row with its key order and JSON types,
so two rows Python calls equal (``True == 1``, one dict against the same
dict with its keys reordered) are two different pages, and the store's
answer is served only when it is byte for byte the document's.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

from ...api.run_store_serving import (
    MEMORY_BY_DESIGN_REASONS,
    SERVING_REASON_DIVERGENT,
    SERVING_SOURCE_MEMORY,
    RunStoreServingOutcome,
    ServedAuthorityCandidates,
    ServedRunSlices,
    ServedUnitLocation,
    read_run_store_authority_candidates,
    read_run_store_slices,
)
from ...observability import record_counter
from ._authority_candidates import authority_candidate_items
from ._session_shared import MCPRunRecord

_ServedT = TypeVar("_ServedT")


def memory_slices(record: MCPRunRecord) -> ServedRunSlices:
    """What the record holds, in the served value shape."""
    return ServedRunSlices(
        run_id=record.run_id,
        unit_inventory=tuple(
            ServedUnitLocation(
                qualname=unit.qualname,
                path=unit.path,
                start_line=unit.start_line,
                end_line=unit.end_line,
            )
            for unit in record.unit_inventory
        ),
        relationship_facts=record.relationship_facts,
        module_imports=record.module_imports,
    )


def _agrees(stored: ServedRunSlices, memory: ServedRunSlices) -> bool:
    """Field-for-field, order-sensitive: the three slices, nothing weaker."""
    return (
        stored.unit_inventory == memory.unit_inventory
        and stored.relationship_facts == memory.relationship_facts
        and stored.module_imports == memory.module_imports
    )


def _shadow_read(
    memory: _ServedT,
    answer: tuple[_ServedT | None, RunStoreServingOutcome],
    *,
    agrees: Callable[[_ServedT, _ServedT], bool],
) -> tuple[_ServedT, RunStoreServingOutcome]:
    """The one serving decision, whatever was read: see the module docstring."""
    stored, outcome = answer
    if stored is None:
        if outcome.reason in MEMORY_BY_DESIGN_REASONS:
            record_counter("run_store_serving_memory")
        else:
            record_counter("run_store_serving_fallback")
        return memory, outcome
    if not agrees(stored, memory):
        record_counter("run_store_serving_divergent")
        return memory, replace(
            outcome, source=SERVING_SOURCE_MEMORY, reason=SERVING_REASON_DIVERGENT
        )
    record_counter("run_store_serving_store_backed")
    return stored, outcome


def served_slices(
    record: MCPRunRecord,
) -> tuple[ServedRunSlices, RunStoreServingOutcome]:
    """The slices to serve for one record, and where they came from."""
    memory = memory_slices(record)
    return _shadow_read(
        memory,
        read_run_store_slices(
            root=record.root, link=record.execution.run_snapshot_link
        ),
        agrees=_agrees,
    )


def memory_authority_candidates(record: MCPRunRecord) -> ServedAuthorityCandidates:
    """The candidate rows the record's sealed document ranked, as served."""
    return ServedAuthorityCandidates(
        run_id=record.run_id,
        items=authority_candidate_items(record.served_report),
    )


def _candidates_wire(served: ServedAuthorityCandidates) -> str:
    return json.dumps([dict(item) for item in served.items], ensure_ascii=False)


def _candidates_agree(
    stored: ServedAuthorityCandidates, memory: ServedAuthorityCandidates
) -> bool:
    """Byte for byte on the wire: row order, key order, values, JSON types."""
    return _candidates_wire(stored) == _candidates_wire(memory)


def served_authority_candidates(
    record: MCPRunRecord,
) -> tuple[ServedAuthorityCandidates, RunStoreServingOutcome]:
    """The candidate rows to page for one record, and where they came from."""
    memory = memory_authority_candidates(record)
    return _shadow_read(
        memory,
        read_run_store_authority_candidates(
            root=record.root, link=record.execution.run_snapshot_link
        ),
        agrees=_candidates_agree,
    )


__all__ = [
    "memory_authority_candidates",
    "memory_slices",
    "served_authority_candidates",
    "served_slices",
]
