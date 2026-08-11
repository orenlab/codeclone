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
from typing import Final, Literal

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

#: Every typed reason on which ingest refuses a whole run. Declared beside the
#: reasons themselves so the set cannot drift from them, and iterated by the
#: guard that requires each one to ship a remedy naming a tool: a population
#: state added later cannot grow a refusal that leaves its caller with no move.
REFUSAL_REASONS: Final[frozenset[str]] = frozenset({REFUSAL_UNMEASURED})

#: Who is being told. The remedy is one fact; only the way each audience
#: invokes it differs, so this selects a spelling and never a meaning.
RefusalSurface = Literal["cli", "mcp"]


def _refusal_commands(*, surface: RefusalSurface, root: str) -> tuple[str, str]:
    """The two invocations — re-analyse, then re-ingest — for one audience.

    This is the whole of what varies between surfaces. An MCP caller has
    ``analyze_repository`` and ``manage_engineering_memory`` in hand, so
    sending it to a shell for ``codeclone`` would be second-class advice and
    would break the rule the rest of that surface keeps — a typed outcome's
    step names a tool the caller can call. ``run_id`` is optional on the
    refresh, and named here anyway: omitted, it binds to whatever ran last,
    which under concurrent agents is silently the wrong run.

    A pair rather than a record: these two strings are unpacked by their only
    caller on the next line and never travel, so giving them a class would put
    a data shape outside the model store to describe a local intermediate.
    """

    if surface == "mcp":
        return (
            f"call analyze_repository(root={root!r})",
            (
                "call manage_engineering_memory(action='refresh_from_run', "
                f"root={root!r}, run_id=<the run_id it returned>)"
            ),
        )
    return (
        f"run `codeclone {root}`",
        f"re-run `codeclone memory init --root {root}`",
    )


def unmeasured_refusal_message(*, root: str, surface: RefusalSurface) -> str:
    """The whole refusal one audience reads: the cause, then what to do.

    One owner for the substance, and deliberately here rather than in a
    surface: this module already owns the refusal vocabulary
    (:data:`REFUSAL_UNMEASURED`), so a remedy owned by one surface would leave
    every other surface either silent or free to invent a second, drifting
    explanation of the same refusal.

    Rendering per surface is not a second truth. The cause, the order of the
    moves, what to look at and the condition for retrying are stated once,
    below; only :func:`_refusal_commands` differs, and it supplies spelling,
    not meaning. Change the sentence here and both audiences move together —
    which is exactly what a single owner has to mean once there are two of
    them.

    The step is derived from the cause rather than attached to it.
    ``unmeasured`` means the run opened none of the files it found, so
    repeating the ingest unchanged would repeat the refusal: the caller has
    to see *why* nothing was read first — ``inventory.files`` reports found
    against analyzed beside the skip counters that name it — and only then
    re-run the ingest.
    """

    reanalyse, reingest = _refusal_commands(surface=surface, root=root)
    return (
        "Refusing to ingest analysis facts from a run whose health population "
        f"is {UNMEASURED_POPULATION!r}: no file was analysed, so every "
        "extracted fact would describe code this run never read. "
        f"Next step: {reanalyse} and read inventory.files — it "
        "reports how many Python files were found against how many were "
        "analyzed, with the skip counters that name the cause. Once at least "
        "one Python file under that root is readable and parses, "
        f"{reingest}."
    )


def refusal_message(
    *, reason: str | None, root: str, surface: RefusalSurface
) -> str | None:
    """The remedy for one refusal reason, spelled for one surface.

    ``None`` for an unknown reason rather than an exception: the only caller
    is the handler that is already reporting a refusal, so raising here would
    replace a typed refusal with a crash. An unregistered reason therefore
    degrades to a payload with no step — the state that shipped before this
    existed — while the guard over :data:`REFUSAL_REASONS` keeps that state
    from reaching a release.
    """

    if reason == REFUSAL_UNMEASURED:
        return unmeasured_refusal_message(root=root, surface=surface)
    return None


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
    "REFUSAL_REASONS",
    "REFUSAL_UNMEASURED",
    "RUN_FITNESS_EVIDENCE_KIND",
    "UNKNOWN",
    "UNMEASURED_POPULATION",
    "RefusalSurface",
    "RunFitness",
    "read_run_fitness",
    "refusal_message",
    "run_fitness_evidence",
    "run_fitness_evidence_id",
    "unmeasured_refusal_message",
]
