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

Three readings go through that one decision (:func:`_shadow_read`), each
with its own memory side and its own agreement: the three slices of
``search_graph`` / ``get_implementation_context``, the authority candidate
rows ``check_authority(section="candidates")`` pages, and the run summary
(``get_run_summary``, consumer migration C1).  The candidates' memory is
the sealed document's own rows, and their agreement is the WIRE: a page
serializes each row with its key order and JSON types, so two rows Python
calls equal (``True == 1``, one dict against the same dict with its keys
reordered) are two different pages, and the store's answer is served only
when it is byte for byte the document's.

The run summary agrees on the wire too, over the WHOLE answer: the store's
blocks are placed into the answer the surface built, every field the store
does not carry (identity, version, provenance, schema, cache, warnings,
failures, drift, hints, the interpreter keys of ``baseline``, the
inventory's ``entity_counts`` branch, the presentation keys of
``security_surfaces``) stays the surface's, and the store's answer is
served only when the two answers are the same bytes.  A disagreement names
every field it found in ``serving.detail``, so a divergence on the desk
says WHICH fields, not merely that one exists.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Final, TypeVar

from ...api.run_store_serving import (
    MEMORY_BY_DESIGN_REASONS,
    SERVING_REASON_DIVERGENT,
    SERVING_SOURCE_MEMORY,
    RunStoreServingOutcome,
    ServedAuthorityCandidates,
    ServedRunSlices,
    ServedRunSummary,
    ServedUnitLocation,
    read_run_store_authority_candidates,
    read_run_store_slices,
    read_run_store_summary,
)
from ...observability import record_counter
from ...utils.coerce import as_mapping
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


#: ``baseline`` keys the surface states beside the stored witness: the
#: interpreter that ran, an execution fact.
EXECUTION_BASELINE_KEYS: Final[tuple[str, ...]] = (
    "runtime_python_tag",
    "interpreter_provenance",
)
#: ``security_surfaces`` keys that are the surface's presentation.
PRESENTATION_SECURITY_KEYS: Final[tuple[str, ...]] = ("report_only", "note")
#: The inventory refusal the surface states instead of ``functions`` /
#: ``classes`` when the report's inventory scope is not the analysis root.
ENTITY_COUNTS_KEY: Final = "entity_counts"
#: The inventory counts the store states on both inventory branches.
_INVENTORY_POPULATION_KEYS: Final[tuple[str, ...]] = ("files", "lines")


def _kept(block: object, keys: tuple[str, ...]) -> dict[str, object]:
    mapping = as_mapping(block)
    return {key: mapping[key] for key in keys if key in mapping}


def _inventory_block(
    memory_inventory: Mapping[str, object], stored: Mapping[str, object]
) -> dict[str, object]:
    """The stored counts, on the inventory branch the surface took."""
    if ENTITY_COUNTS_KEY not in memory_inventory:
        return dict(stored)
    return {
        **_kept(stored, _INVENTORY_POPULATION_KEYS),
        ENTITY_COUNTS_KEY: memory_inventory[ENTITY_COUNTS_KEY],
    }


def _security_block(
    memory_block: object, stored: Mapping[str, object]
) -> dict[str, object]:
    """The stored counts with the surface's presentation keys, or the stored
    metrics-skipped word as it stands."""
    if stored.get("available") is False:
        return dict(stored)
    return {**stored, **_kept(memory_block, PRESENTATION_SECURITY_KEYS)}


def _place(payload: dict[str, object], key: str, block: Mapping[str, object]) -> None:
    """A block the surface omits when it has nothing to say."""
    if block:
        payload[key] = dict(block)
    else:
        payload.pop(key, None)


def store_summary_payload(
    memory: Mapping[str, object], stored: ServedRunSummary
) -> dict[str, object]:
    """The run summary built from the store's blocks.

    Every field the store does not carry is the surface's own answer, so
    the two payloads can differ only where the store and the memory do.
    """
    payload = dict(memory)
    payload["mode"] = stored.mode
    payload["baseline"] = {
        **stored.baseline,
        **_kept(memory.get("baseline"), EXECUTION_BASELINE_KEYS),
    }
    payload["metrics_baseline"] = dict(stored.metrics_baseline)
    payload["inventory"] = _inventory_block(
        as_mapping(memory.get("inventory")), stored.inventory
    )
    payload["health"] = dict(stored.health)
    payload["findings"] = dict(stored.findings)
    payload["diff"] = dict(stored.diff)
    _place(payload, "analysis_profile", stored.analysis_profile)
    _place(payload, "dead_code", stored.dead_code)
    _place(payload, "coverage_join", stored.coverage_join)
    _place(
        payload,
        "security_surfaces",
        _security_block(memory.get("security_surfaces"), stored.security_surfaces),
    )
    return payload


def _summary_wire(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _summary_agrees(stored: dict[str, object], memory: dict[str, object]) -> bool:
    """Byte for byte on the wire: every field, its key order, its JSON type."""
    return _summary_wire(stored) == _summary_wire(memory)


def _keys_of(first: Mapping[str, object], second: Mapping[str, object]) -> list[str]:
    return [*first, *(key for key in second if key not in first)]


def _same_field(
    stored: Mapping[str, object], memory: Mapping[str, object], key: str
) -> bool:
    if (key in stored) != (key in memory):
        return False
    return _summary_wire(stored.get(key)) == _summary_wire(memory.get(key))


def summary_divergence(
    stored: Mapping[str, object], memory: Mapping[str, object]
) -> tuple[str, ...]:
    """The fields where the two answers differ: a block by its differing
    keys, and the block itself when only its key order differs."""
    fields: list[str] = []
    for key in _keys_of(memory, stored):
        if _same_field(stored, memory, key):
            continue
        stored_block, memory_block = stored.get(key), memory.get(key)
        if isinstance(stored_block, Mapping) and isinstance(memory_block, Mapping):
            inner = [
                f"{key}.{name}"
                for name in _keys_of(memory_block, stored_block)
                if not _same_field(stored_block, memory_block, name)
            ]
            fields.extend(inner or [key])
        else:
            fields.append(key)
    if not fields and _summary_wire(stored) != _summary_wire(memory):
        fields.append("<field order>")
    return tuple(fields)


def _named_divergence(
    outcome: RunStoreServingOutcome,
    candidate: Mapping[str, object] | None,
    memory: Mapping[str, object],
) -> RunStoreServingOutcome:
    """A divergent outcome with the fields that diverged joined to the
    door's own detail; any other outcome as it stands."""
    if outcome.reason != SERVING_REASON_DIVERGENT or candidate is None:
        return outcome
    named = "diverging: " + ", ".join(summary_divergence(candidate, memory))
    return replace(
        outcome, detail="; ".join(part for part in (outcome.detail, named) if part)
    )


def served_run_summary(
    record: MCPRunRecord, memory: Mapping[str, object]
) -> tuple[dict[str, object], RunStoreServingOutcome]:
    """The run summary to answer for one record, and where it came from.

    ``memory`` is the answer the surface built from the record; the store's
    is built from it and the store's blocks, and served only when the two
    are the same bytes.
    """
    stored, outcome = read_run_store_summary(
        root=record.root, link=record.execution.run_snapshot_link
    )
    candidate = None if stored is None else store_summary_payload(memory, stored)
    payload, served = _shadow_read(
        dict(memory), (candidate, outcome), agrees=_summary_agrees
    )
    return payload, _named_divergence(served, candidate, memory)


__all__ = [
    "ENTITY_COUNTS_KEY",
    "EXECUTION_BASELINE_KEYS",
    "PRESENTATION_SECURITY_KEYS",
    "memory_authority_candidates",
    "memory_slices",
    "served_authority_candidates",
    "served_run_summary",
    "served_slices",
    "store_summary_payload",
    "summary_divergence",
]
