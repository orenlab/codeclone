# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Ask the analysing run whether it was fit to be believed.

A report already states the two facts that decide this, and both are owned
elsewhere: ``compute_health`` classifies how much of the found population the
run actually observed, and the baseline projection collapses the per-lane
trust vector into ``baseline.state``. Nothing here re-derives either of them
from the file counters beside them — that would be a second owner of one
fact, and the two owners would drift. This module reads, names, and carries.

The reading is deliberately tolerant in one direction only. An absent fact
becomes ``"unknown"``, never a verdict: a report that predates a field, or a
run with no health family at all, has not told us it was unfit, and refusing
on silence would be an invented finding.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from ...models import RunFitness
from ...utils.coerce import as_mapping, as_sequence
from ...utils.mapping_paths import section
from ..enums import EvidenceKind
from ..models import MemoryEvidence, MemoryRecord

#: Evidence lane the run-fitness mark rides in. ``report`` is the existing
#: ``EvidenceKind`` for "this record came out of an analysis report"; the mark
#: is a property of that report, not a new species of evidence.
RUN_FITNESS_EVIDENCE_KIND: EvidenceKind = "report"

#: Named because it is not a measurement: the report did not state the fact.
UNKNOWN = "unknown"

#: The one population state that leaves nothing to believe. ``partial`` runs
#: measured something real; only this one measured nothing at all.
UNMEASURED_POPULATION = "unmeasured"

REFUSAL_UNMEASURED = "health_population_unmeasured"


def _stated(value: object) -> str:
    text = str(value or "").strip()
    return text or UNKNOWN


def _untrusted_lanes(baseline: Mapping[str, object]) -> tuple[str, ...]:
    names = {
        str(row.get("name", "")).strip()
        for item in as_sequence(baseline.get("sorted_lane_trust"))
        for row in (as_mapping(item),)
        if str(row.get("status", "")).strip() != "trusted"
    }
    return tuple(sorted(name for name in names if name))


def read_run_fitness(report_document: Mapping[str, object]) -> RunFitness:
    """Project one report's own fitness facts, without re-measuring them."""

    health = section(report_document, "metrics.families.health.summary")
    baseline = as_mapping(report_document.get("baseline"))
    population = _stated(health.get("population"))
    unmeasured = population == UNMEASURED_POPULATION
    return RunFitness(
        population=population,
        baseline_state=_stated(baseline.get("state")),
        untrusted_lanes=_untrusted_lanes(baseline),
        ingestible=not unmeasured,
        refusal_reason=REFUSAL_UNMEASURED if unmeasured else None,
    )


def run_fitness_evidence_id(identity_key: str) -> str:
    """One stable mark id per record identity.

    Deliberately not a fresh uuid. ``write_evidence`` is INSERT OR REPLACE on
    the id, so a random id would append a second mark on every refresh and a
    reader would face a pile of contradictory fitness claims for one record
    with no rule for picking one. Keyed on identity, the current run's mark
    replaces the previous run's — which is the truth: this record's content
    now comes from this run.
    """

    digest = hashlib.sha256(identity_key.encode("utf-8")).hexdigest()
    return f"evid-fitness-{digest[:32]}"


def run_fitness_evidence(
    *,
    record: MemoryRecord,
    fitness: RunFitness,
    analysis_fingerprint: str | None,
    report_digest: str | None,
    created_at_utc: str,
) -> MemoryEvidence:
    """The per-record mark: which run, and whether that run was fit.

    ``analysis_fingerprint`` already answers *which* run; alone it answers
    only that, which is why a reader could not tell a truncated run's facts
    from a whole one's. The fitness rides in ``locator`` beside it.
    """

    return MemoryEvidence(
        id=run_fitness_evidence_id(record.identity_key),
        memory_id=record.id,
        evidence_kind=RUN_FITNESS_EVIDENCE_KIND,
        ref=analysis_fingerprint or UNKNOWN,
        locator=fitness.provenance,
        # Not the refusal reason: a refused run never reaches storage, so a
        # field for it here would be one no input could ever fill.
        quote=None,
        digest=report_digest,
        created_at_utc=created_at_utc,
    )


__all__ = [
    "REFUSAL_UNMEASURED",
    "RUN_FITNESS_EVIDENCE_KIND",
    "UNKNOWN",
    "UNMEASURED_POPULATION",
    "RunFitness",
    "read_run_fitness",
    "run_fitness_evidence",
    "run_fitness_evidence_id",
]
