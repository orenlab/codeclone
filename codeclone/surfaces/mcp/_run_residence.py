# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What stays of a run when its payload goes, and when it may go.

The session holds a run whole while its payload -- the served report
projection, the summary, the per-file tables -- is in memory, and by its
resident identity alone once the payload was dropped
(``_session_shared.MCPRunIdentity``).  What that identity holds is decided
here; when the payload may go is decided beside it:

* :func:`resident_identity` -- the identity a record is held by after the
  drop: its resident fields, plus the run summary's memory-only fields
  copied out of the payload;
* when it may go is the one drop rule, ``api.run_residence.payload_droppable``:
  only while the run store can stand in for the payload -- the execution
  published and linked its run, the store serves the migrated readings,
  every intent pinning the run holds its store lease, and the run's
  membership is proven by its object ids.  Anything else keeps the payload,
  as before the rule existed.

How many payloads are held is the history limit's
(``CodeCloneMCPRunStore.payload_excess``); which go first is the oldest
(``_session_run_payload_mixin``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Final

from ... import __version__
from ...api.run_residence import RunSummaryResidue
from ...api.run_store_serving import (
    BlastRadiusFacts,
    RunStoreServingOutcome,
    read_run_store_blast_radius_facts,
    read_run_store_summary,
)
from ...utils.coerce import as_mapping
from . import _session_helpers as _helpers
from ._blast_radius import BlastRadiusResult
from ._run_store_serving import (
    ENTITY_COUNTS_KEY,
    EXECUTION_BASELINE_KEYS,
    PRESENTATION_SECURITY_KEYS,
    _kept,
    store_summary_payload,
)
from ._session_shared import (
    _FOCUS_REPOSITORY,
    _HEALTH_SCOPE_REPOSITORY,
    MCPHeldRun,
    MCPRunIdentity,
    MCPRunPayloadEvictedError,
    MCPRunRecord,
)
from ._workspace_drift import compute_drift
from .messages.run_payload import (
    PAYLOAD_EVICTED,
    payload_evicted_message,
    payload_evicted_next_step,
)

#: ``serving.detail`` of a store answer served for a run without its payload.
SERVING_DETAIL_PAYLOAD_EVICTED: Final = PAYLOAD_EVICTED
#: ``status`` of the typed refusal: the run is known and cannot be answered.
PAYLOAD_EVICTED_STATUS: Final = "unavailable"


def summary_residue(record: MCPRunRecord) -> RunSummaryResidue:
    """The run summary's memory-only fields, read as the summary reads them
    (``_session_state_mixin._summary_payload``)."""
    summary = record.summary
    inventory = _helpers._summary_inventory_payload(
        as_mapping(summary.get("inventory"))
    )
    entity_counts = inventory.get(ENTITY_COUNTS_KEY)
    return RunSummaryResidue(
        version=str(summary.get("codeclone_version", __version__)),
        schema=str(summary.get("report_schema_version", "")),
        cache=_helpers._summary_cache_payload(summary),
        baseline_execution=_kept(
            _helpers._summary_trusted_state_payload(summary, key="baseline"),
            EXECUTION_BASELINE_KEYS,
        ),
        entity_counts=None if entity_counts is None else as_mapping(entity_counts),
        security_presentation=_kept(
            _helpers._summary_security_surfaces_payload(record),
            PRESENTATION_SECURITY_KEYS,
        ),
    )


def resident_identity(record: MCPRunRecord) -> MCPRunIdentity:
    """The identity ``record`` is held by once its payload is dropped."""
    return MCPRunIdentity(
        run_id=record.run_id,
        root=record.root,
        request=record.request,
        comparison_settings=record.comparison_settings,
        changed_paths=record.changed_paths,
        func_clones_count=record.func_clones_count,
        block_clones_count=record.block_clones_count,
        execution=record.execution,
        summary_residue=summary_residue(record),
    )


def report_digest_of(held: MCPHeldRun) -> str:
    """The report digest of a held run: off its document while it is held
    whole; after the drop, its run id -- which IS the report's evaluation
    digest (``session.analyze_repository`` names the run by it)."""
    if isinstance(held, MCPRunRecord):
        return _helpers._report_digest(held.served_report)
    return held.run_id


def payload_evicted_outcome(outcome: RunStoreServingOutcome) -> RunStoreServingOutcome:
    """A store answer served for a run without its payload says so: no
    memory answer was there to agree with."""
    return replace(
        outcome,
        detail="; ".join(
            part for part in (outcome.detail, SERVING_DETAIL_PAYLOAD_EVICTED) if part
        ),
    )


def payload_evicted_answer(
    identity: MCPRunIdentity,
    *,
    serving: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """The one answer about a held run without its payload that no store
    reading stood in for -- a tool without a store road, or a store road
    the store refused (its ``serving`` block then says why)."""
    run_id = _helpers._short_run_id(identity.run_id)
    answer: dict[str, object] = {
        "run_id": run_id,
        "root": str(identity.root),
        "status": PAYLOAD_EVICTED_STATUS,
        "reason": PAYLOAD_EVICTED,
        "next_step": payload_evicted_next_step(root=str(identity.root), run_id=run_id),
        "message": payload_evicted_message(run_id=run_id),
    }
    if serving is not None:
        answer["serving"] = dict(serving)
    return answer


def _resident_summary_frame(
    identity: MCPRunIdentity, *, code_provenance: Mapping[str, object]
) -> dict[str, object]:
    """The run summary of a run without its payload before the store's
    blocks are placed in it (``_run_store_serving.store_summary_payload``):
    every field where the memory answer has it, the memory-only ones off the
    resident identity, the store-carried ones empty -- the store fills them,
    or drops the optional ones it has nothing for."""
    residue = identity.summary_residue
    payload: dict[str, object] = {
        "run_id": _helpers._short_run_id(identity.run_id),
        "focus": _FOCUS_REPOSITORY,
        "health_scope": _HEALTH_SCOPE_REPOSITORY,
        "version": residue.version,
        "code_provenance": dict(code_provenance),
        "schema": residue.schema,
        "mode": "",
        "baseline": dict(residue.baseline_execution),
        "metrics_baseline": {},
        "cache": dict(residue.cache),
        "inventory": (
            {}
            if residue.entity_counts is None
            else {ENTITY_COUNTS_KEY: dict(residue.entity_counts)}
        ),
        "health": {},
        "findings": {},
        "diff": {},
        "warnings": list(identity.execution.warnings),
        "failures": list(identity.execution.failures),
        "analysis_profile": {},
        "dead_code": {},
        "coverage_join": {},
        "security_surfaces": dict(residue.security_presentation),
        "drifted_files": list(compute_drift(identity).drifted_files),
        "next_tool": "get_production_triage",
    }
    _helpers.attach_workspace_hygiene_tips(payload, root=identity.root)
    return payload


def payload_evicted_run_summary(
    identity: MCPRunIdentity, *, code_provenance: Mapping[str, object]
) -> dict[str, object]:
    """``get_run_summary`` of a run without its payload: the store's blocks
    in the resident frame, served on the strength of the door's membership
    proof alone -- there is no memory answer to agree with.  A store that
    cannot answer is the typed refusal, never an emptied summary."""
    stored, outcome = read_run_store_summary(
        root=identity.root, link=identity.execution.run_snapshot_link
    )
    if stored is None:
        raise MCPRunPayloadEvictedError(identity, serving=outcome.as_payload())
    payload = store_summary_payload(
        _resident_summary_frame(identity, code_provenance=code_provenance), stored
    )
    payload["serving"] = payload_evicted_outcome(outcome).as_payload()
    return payload


def payload_evicted_blast_radius(
    identity: MCPRunIdentity,
    compute: Callable[[BlastRadiusFacts], BlastRadiusResult],
) -> tuple[BlastRadiusResult, RunStoreServingOutcome]:
    """The blast radius of a run without its payload: ``compute`` over the
    facts the store states for the execution, on the strength of the door's
    membership proof -- or the typed refusal when the store states none."""
    facts, outcome = read_run_store_blast_radius_facts(
        root=identity.root, link=identity.execution.run_snapshot_link
    )
    if facts is None:
        raise MCPRunPayloadEvictedError(identity, serving=outcome.as_payload())
    return compute(facts), payload_evicted_outcome(outcome)


__all__ = [
    "PAYLOAD_EVICTED",
    "SERVING_DETAIL_PAYLOAD_EVICTED",
    "payload_evicted_answer",
    "payload_evicted_blast_radius",
    "payload_evicted_outcome",
    "payload_evicted_run_summary",
    "report_digest_of",
    "resident_identity",
    "summary_residue",
]
