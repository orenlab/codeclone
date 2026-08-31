# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The unified GC point's runtime: the R3 door that dispatches jobs.

The maintainer's form (2026-08-31): one dispatcher/orchestrator and
different jobs — the logic is one, and the small jobs are surface-custom,
under one shared protocol.  The protocol contract — reason vocabularies, the
report's honesty arithmetic, the hold-deadline law — lives in the model
store (``codeclone.models``); this door owns everything a dispatch does
identically for every surface:

* deterministic dispatch order (sorted by job name, duplicates refused);
* refusal as a typed, visible outcome — an anticipated refusal is a
  report, an escaping exception is a defect and propagates raw;
* per-job atomicity honesty: each job commits alone in its own storage,
  the orchestrator never pretends to atomicity ACROSS storages — a crash
  between jobs leaves finished jobs finished and unstarted jobs untouched;
* the observation.  Observation belongs to the orchestrator, not to jobs:
  a job answers through the protocol and the answer becomes the one
  telemetry dialect, so three collecting surfaces cannot mint three
  dictionaries about one event.  Every observation carries the DECISION —
  which root held, which verdict collected, which job answered, whether it
  refused — because GC is debugged when it collected too much or too
  little, and both questions are "why".

This door also re-exports the protocol surface so R4 consumers reach the
whole unified GC point through one import.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from ..models import (
    GC_COLLECT_CORRUPT,
    GC_COLLECT_EXPIRED,
    GC_COLLECT_ORPHANED,
    GC_COLLECT_REASONS,
    GC_COLLECT_UNREACHABLE,
    GC_HOLD_HEAD,
    GC_HOLD_HISTORY,
    GC_HOLD_LEASE,
    GC_HOLD_OWNER_ALIVE,
    GC_HOLD_REASONS,
    GC_HOLD_RETAINED,
    GC_HOLD_STAGING,
    GcJob,
    GcJobReport,
    GcProtocolError,
    GcRunReceipt,
    deadline_passed,
)
from ..observability import SpanHandle, span

_RUN_SPAN: Final = "gc.run"
_JOB_SPAN: Final = "gc.collect"

# One counter per closed reason, spelled here because the vocabulary is the
# protocol's, not a job's — a reason without a counter would be a decision
# invisible to debugging.
_HELD_COUNTERS: Final[Mapping[str, str]] = {
    GC_HOLD_HEAD: "gc_held_head",
    GC_HOLD_HISTORY: "gc_held_history",
    GC_HOLD_LEASE: "gc_held_lease",
    GC_HOLD_RETAINED: "gc_held_retained",
    GC_HOLD_STAGING: "gc_held_staging",
    GC_HOLD_OWNER_ALIVE: "gc_held_owner_alive",
}
_COLLECTED_COUNTERS: Final[Mapping[str, str]] = {
    GC_COLLECT_EXPIRED: "gc_collected_expired",
    GC_COLLECT_ORPHANED: "gc_collected_orphaned",
    GC_COLLECT_UNREACHABLE: "gc_collected_unreachable",
    GC_COLLECT_CORRUPT: "gc_collected_corrupt",
}


def _emit_job_observation(handle: SpanHandle, report: GcJobReport) -> None:
    """Turn one report into one observation, zero-filled over the closed
    vocabulary: an absent magnitude cannot be told apart from a span that
    never reached the site, so every reason is written, zero included.
    An uncollected object is explainable from the span without reading
    code; a refusal is a visible event, never silence."""
    handle.set_counter("gc_candidates", report.candidates)
    for reason in sorted(GC_HOLD_REASONS):
        handle.set_counter(_HELD_COUNTERS[reason], report.held_count(reason))
    for reason in sorted(GC_COLLECT_REASONS):
        handle.set_counter(_COLLECTED_COUNTERS[reason], report.collected_count(reason))
    handle.set_counter("gc_job_refused", 0 if report.refusal is None else 1)


def run_gc(jobs: Sequence[GcJob]) -> GcRunReceipt:
    """Dispatch every job once, deterministically, and observe each answer.

    Jobs run in sorted-name order under one ``gc.run`` span; each job gets
    its own ``gc.collect`` span carrying the job's name as the span reason.
    A report that lies about its job identity is refused loudly.  The
    dispatch counters are written in ``finally`` so a defect escaping from
    a job still leaves the run measured as far as it got.
    """
    ordered = sorted(jobs, key=lambda job: job.name)
    names = [job.name for job in ordered]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise GcProtocolError(f"duplicate GC job names: {duplicated!r}")
    reports: list[GcJobReport] = []
    collected_jobs = 0
    refused_jobs = 0
    with span(name=_RUN_SPAN) as run_span:
        try:
            for job in ordered:
                with span(name=_JOB_SPAN, reason=job.name) as job_span:
                    report = job.collect()
                    if report.job != job.name:
                        raise GcProtocolError(
                            f"job {job.name!r} answered for {report.job!r}"
                        )
                    _emit_job_observation(job_span, report)
                if report.refusal is None:
                    collected_jobs += 1
                else:
                    refused_jobs += 1
                reports.append(report)
        finally:
            run_span.set_counter("gc_jobs_dispatched", len(ordered))
            run_span.set_counter("gc_jobs_collected", collected_jobs)
            run_span.set_counter("gc_jobs_refused", refused_jobs)
    return GcRunReceipt(reports=tuple(reports))


__all__ = [
    "GC_COLLECT_CORRUPT",
    "GC_COLLECT_EXPIRED",
    "GC_COLLECT_ORPHANED",
    "GC_COLLECT_REASONS",
    "GC_COLLECT_UNREACHABLE",
    "GC_HOLD_HEAD",
    "GC_HOLD_HISTORY",
    "GC_HOLD_LEASE",
    "GC_HOLD_OWNER_ALIVE",
    "GC_HOLD_REASONS",
    "GC_HOLD_RETAINED",
    "GC_HOLD_STAGING",
    "GcJob",
    "GcJobReport",
    "GcProtocolError",
    "GcRunReceipt",
    "deadline_passed",
    "run_gc",
]
