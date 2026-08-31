# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The unified GC point: protocol laws, orchestrator laws, and the proof
that the protocol is real on two production surfaces in one dispatch —
the canonical run-store job next to the observability retention collector
wrapped as a job (the workspace-intent collector is proven in its own
ring, tests/test_gc_workspace_intent_job.py).

The observation laws live here too, because observation belongs to the
orchestrator: one closed name family, emitted from exactly one module,
decisions and refusals visible, and an OFF/ON witness proving the observer
changes nothing but the telemetry.
"""

from __future__ import annotations

import ast
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import orjson
import pytest

from codeclone.api.gc import _COLLECTED_COUNTERS, _HELD_COUNTERS, run_gc
from codeclone.canonical import RunStore, UnknownRunError
from codeclone.canonical import store as store_module
from codeclone.canonical.store import RunStoreGcJob, acquire_run_lease, retain_run
from codeclone.models import (
    GC_COLLECT_EXPIRED,
    GC_COLLECT_REASONS,
    GC_COLLECT_UNREACHABLE,
    GC_HOLD_HEAD,
    GC_HOLD_HISTORY,
    GC_HOLD_REASONS,
    GcJobReport,
    GcProtocolError,
    GcRunReceipt,
    ObservabilityConfig,
    deadline_passed,
)
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.observability.models import OperationRecord
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.observability.store.writer import run_retention_gc, write_operation
from codeclone.observability.vocabulary import COUNTER_KEYS, SPAN_NAMES
from codeclone.workspace_intent import lifecycle
from tests.test_canonical_roundtrip import fixture_model
from tests.test_workspace_intents import _record

_ROOT = Path(__file__).resolve().parents[1]
_GC_DOOR = _ROOT / "codeclone" / "api" / "gc.py"


# -- the one hold-deadline law ----------------------------------------------


def test_the_deadline_law_expires_at_the_deadline_not_after() -> None:
    assert deadline_passed(10, 10) is True
    assert deadline_passed(11, 10) is False
    assert deadline_passed(9, 10) is True
    before = datetime(2026, 8, 31, tzinfo=timezone.utc)
    assert deadline_passed(before, before) is True
    assert deadline_passed(before + timedelta(seconds=1), before) is False


def test_a_missing_deadline_is_a_passed_deadline() -> None:
    """Fail-collectable, never fail-eternal: a grant that cannot prove its
    own liveness does not hold anything."""
    assert deadline_passed(None, 0) is True
    assert deadline_passed(None, datetime(2026, 1, 1, tzinfo=timezone.utc)) is True


def test_intent_lease_expiry_decides_through_the_one_deadline_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The structural edge, both directions: whatever the record says, the
    verdict is whatever the shared law says — so the workspace-intent
    lifecycle cannot drift away from the run-store sweep on the boundary."""
    fresh = _record()
    monkeypatch.setattr(lifecycle, "deadline_passed", lambda deadline, now: True)
    assert lifecycle.is_lease_expired(fresh) is True
    monkeypatch.setattr(lifecycle, "deadline_passed", lambda deadline, now: False)
    assert lifecycle.is_lease_expired(fresh) is False


def test_an_unreadable_renewal_timestamp_is_an_expired_lease() -> None:
    """The None-clause of the law, reached from the intent surface: an
    unparseable renewal timestamp means a passed deadline, not immortality."""
    assert lifecycle.is_lease_expired(_record(lease_renewed_delta=timedelta())) is False
    broken = replace(_record(), lease_renewed_at_utc="not-a-timestamp")
    assert lifecycle.is_lease_expired(broken) is True


# -- report laws ------------------------------------------------------------


def test_a_report_refuses_reasons_outside_the_closed_vocabulary() -> None:
    with pytest.raises(GcProtocolError, match="closed GC vocabulary"):
        GcJobReport.build(job="j", candidates=1, held={"vibes": 1})
    with pytest.raises(GcProtocolError, match="closed GC vocabulary"):
        GcJobReport.build(job="j", candidates=1, collected={"deleted": 1})


def test_a_report_must_balance_candidates_against_held_and_collected() -> None:
    with pytest.raises(GcProtocolError, match="does not balance"):
        GcJobReport.build(
            job="j",
            candidates=3,
            held={GC_HOLD_HEAD: 1},
            collected={GC_COLLECT_EXPIRED: 1},
        )
    balanced = GcJobReport.build(
        job="j",
        candidates=2,
        held={GC_HOLD_HEAD: 1},
        collected={GC_COLLECT_EXPIRED: 1},
    )
    assert balanced.candidates == 2


def test_a_refused_job_makes_no_claims() -> None:
    refused = GcJobReport.refused(job="j", refusal="fence moved")
    assert refused.candidates == 0
    assert refused.held == () and refused.collected == () and refused.detail == ()
    with pytest.raises(GcProtocolError, match="makes no claims"):
        GcJobReport(job="j", candidates=1, refusal="fence moved")
    with pytest.raises(GcProtocolError, match="must say why"):
        GcJobReport(job="j", candidates=0, refusal="")


def test_a_report_refuses_malformed_counts_and_names() -> None:
    with pytest.raises(GcProtocolError, match="name its job"):
        GcJobReport(job="", candidates=0)
    with pytest.raises(GcProtocolError, match="not a count"):
        GcJobReport(job="j", candidates=-1)
    with pytest.raises(GcProtocolError, match="not a count"):
        GcJobReport.build(job="j", candidates=1, held={GC_HOLD_HEAD: -1})
    with pytest.raises(GcProtocolError, match="not a count"):
        GcJobReport.build(job="j", candidates=1, held={GC_HOLD_HEAD: True})
    with pytest.raises(GcProtocolError, match="twice"):
        GcJobReport(job="j", candidates=2, held=((GC_HOLD_HEAD, 1), (GC_HOLD_HEAD, 1)))
    with pytest.raises(GcProtocolError, match="unnamed reason"):
        GcJobReport(job="j", candidates=1, detail=(("", 1),))
    with pytest.raises(GcProtocolError, match="not a count"):
        GcJobReport.build(job="j", candidates=0, detail={"extra": -2})


def test_a_report_is_canonically_ordered_regardless_of_input_order() -> None:
    report = GcJobReport(
        job="j",
        candidates=3,
        held=((GC_HOLD_HISTORY, 1), (GC_HOLD_HEAD, 2)),
        detail=(("z", 1), ("a", 2)),
    )
    assert report.held == ((GC_HOLD_HEAD, 2), (GC_HOLD_HISTORY, 1))
    assert report.detail == (("a", 2), ("z", 1))
    assert report.held_count(GC_HOLD_HEAD) == 2
    assert report.collected_count(GC_COLLECT_EXPIRED) == 0


# -- orchestrator laws -------------------------------------------------------


@dataclass
class _StubJob:
    name: str
    log: list[str]
    report: GcJobReport | None = None
    error: Exception | None = None

    def collect(self) -> GcJobReport:
        self.log.append(self.name)
        if self.error is not None:
            raise self.error
        assert self.report is not None
        return self.report


def _answer(name: str, log: list[str]) -> _StubJob:
    return _StubJob(name=name, log=log, report=GcJobReport(job=name, candidates=0))


def test_jobs_dispatch_in_sorted_name_order_whatever_the_roster_order() -> None:
    log: list[str] = []
    receipt = run_gc([_answer("bravo", log), _answer("alpha", log)])
    assert log == ["alpha", "bravo"]
    assert [report.job for report in receipt.reports] == ["alpha", "bravo"]


def test_duplicate_job_names_are_refused_before_anything_runs() -> None:
    log: list[str] = []
    with pytest.raises(GcProtocolError, match="duplicate GC job names"):
        run_gc([_answer("same", log), _answer("same", log)])
    assert log == []


def test_a_report_that_lies_about_its_job_identity_is_refused() -> None:
    log: list[str] = []
    impostor = _StubJob(
        name="honest", log=log, report=GcJobReport(job="other", candidates=0)
    )
    with pytest.raises(GcProtocolError, match="answered for"):
        run_gc([impostor])


def test_a_defect_escaping_a_job_propagates_raw_after_earlier_jobs_ran() -> None:
    """Anticipated refusals are reports; an escaping exception is a defect
    and stays loud.  Jobs already finished stay finished — their storages
    committed alone — and the log proves how far the dispatch got."""
    log: list[str] = []
    with pytest.raises(RuntimeError, match="defect"):
        run_gc(
            [
                _StubJob(name="b-broken", log=log, error=RuntimeError("defect")),
                _answer("a-fine", log),
            ]
        )
    assert log == ["a-fine", "b-broken"]


def test_an_empty_roster_is_an_answered_empty_receipt() -> None:
    assert run_gc([]) == GcRunReceipt(reports=())


# -- observation: emitted from the orchestrator, decisions visible -----------


def _module_string_literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_the_gc_name_family_is_declared_and_spelled_in_the_orchestrator() -> None:
    """Both directions of the inventory: every declared gc_* counter and
    gc.* span is spelled in the orchestrator door, and the counter maps
    cover the closed reason vocabularies exactly — a reason without a
    counter would be an invisible decision."""
    declared_counters = {key for key in COUNTER_KEYS if key.startswith("gc_")}
    declared_spans = {name for name in SPAN_NAMES if name.startswith("gc.")}
    literals = _module_string_literals(_GC_DOOR)
    assert declared_spans == {"gc.collect", "gc.run"}
    assert declared_counters <= literals
    assert declared_spans <= literals
    assert set(_HELD_COUNTERS) == GC_HOLD_REASONS
    assert set(_COLLECTED_COUNTERS) == GC_COLLECT_REASONS
    assert (
        set(_HELD_COUNTERS.values())
        | set(_COLLECTED_COUNTERS.values())
        | {
            "gc_candidates",
            "gc_job_refused",
            "gc_jobs_collected",
            "gc_jobs_dispatched",
            "gc_jobs_refused",
        }
        == declared_counters
    )


def test_no_other_production_module_speaks_the_gc_observation_family() -> None:
    """One event, one dialect: the orchestrator is the only emitter, so a
    second module minting gc_* names would be the three-dictionaries split
    the unified point exists to prevent."""
    declared = {key for key in COUNTER_KEYS if key.startswith("gc_")} | {
        name for name in SPAN_NAMES if name.startswith("gc.")
    }
    offenders = []
    for path in sorted((_ROOT / "codeclone").rglob("*.py")):
        if path == _GC_DOOR or path.name == "vocabulary.py":
            continue
        if declared & _module_string_literals(path):
            offenders.append(str(path.relative_to(_ROOT)))
    assert offenders == []


def _span_rows(root: Path, name: str) -> list[tuple[str | None, dict[str, int]]]:
    """(reason, counters) of every span with this name, in write order."""
    store = root / ".codeclone" / "db" / "platform_observability.sqlite3"
    connection = sqlite3.connect(store)
    try:
        rows = connection.execute(
            "SELECT reason, counters_json FROM platform_spans "
            "WHERE name=? ORDER BY rowid",
            (name,),
        ).fetchall()
    finally:
        connection.close()
    return [
        (
            reason,
            {
                str(key): int(value)
                for key, value in (orjson.loads(raw) if raw else {}).items()
            },
        )
        for reason, raw in rows
    ]


def test_the_observation_carries_the_decision_zero_filled(tmp_path: Path) -> None:
    """One gc.run span for the orchestration, one gc.collect span per job
    with the job's name as the span reason; every reason counter written,
    zero included — an uncollected object is explainable from the span
    without reading code, and an absent magnitude cannot be confused with
    a site never reached."""
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with (
            operation(name="mcp.analyze_repository", surface="mcp"),
            RunStore(tmp_path / "runs.sqlite") as store,
        ):
            store.write_full_run(
                fixture_model(),
                namespace="observed",
                target="head",
                expected_generation=0,
            )
            run_gc([RunStoreGcJob(store=store, retain_history=1)])
    finally:
        shutdown()

    runs = _span_rows(tmp_path, "gc.run")
    assert len(runs) == 1
    assert runs[0][1] == {
        "gc_jobs_dispatched": 1,
        "gc_jobs_collected": 1,
        "gc_jobs_refused": 0,
    }
    collects = _span_rows(tmp_path, "gc.collect")
    assert len(collects) == 1
    reason, counters = collects[0]
    assert reason == "canonical_run_store"
    assert counters == {
        "gc_candidates": 1,
        "gc_held_head": 1,
        "gc_held_history": 0,
        "gc_held_lease": 0,
        "gc_held_owner_alive": 0,
        "gc_held_retained": 0,
        "gc_held_staging": 0,
        "gc_collected_corrupt": 0,
        "gc_collected_expired": 0,
        "gc_collected_orphaned": 0,
        "gc_collected_unreachable": 0,
        "gc_job_refused": 0,
    }


def test_a_job_refusal_is_a_visible_event_not_silence(tmp_path: Path) -> None:
    """Silence is indistinguishable from "nothing to collect", so a refusal
    must land on both spans: the job's own gc_job_refused and the run's
    gc_jobs_refused."""
    path = tmp_path / "runs.sqlite"
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with (
            operation(name="mcp.analyze_repository", surface="mcp"),
            RunStore(path) as stale,
            RunStore(path) as mover,
        ):
            stale.write_full_run(
                fixture_model(),
                namespace="observed",
                target="head",
                expected_generation=0,
            )
            mover.bump_store_epoch()
            receipt = run_gc([RunStoreGcJob(store=stale, retain_history=1)])
    finally:
        shutdown()

    assert receipt.reports[0].refusal is not None
    assert _span_rows(tmp_path, "gc.run")[0][1]["gc_jobs_refused"] == 1
    collects = _span_rows(tmp_path, "gc.collect")
    assert collects[0][1]["gc_job_refused"] == 1
    assert collects[0][1]["gc_candidates"] == 0


# -- the observer changes nothing but the telemetry --------------------------


def _store_contents(path: Path) -> dict[str, list[tuple[object, ...]]]:
    connection = sqlite3.connect(path)
    try:
        tables = [
            str(name)
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            table: sorted(connection.execute(f"SELECT * FROM {table}"))
            for table in tables
        }
    finally:
        connection.close()


def _sweep_story(root: Path) -> tuple[GcRunReceipt, bytes]:
    """The same publish/lease/retain/sweep story, wherever the observer
    decision is frozen."""
    model = fixture_model()
    wider = replace(
        model,
        coupled_sets=frozenset(set(model.coupled_sets) | {frozenset({"OnlyInWide"})}),
    )
    with RunStore(root / "runs.sqlite") as store:
        first = store.write_full_run(
            model, namespace="witness", target="head", expected_generation=0
        )
        second = store.write_full_run(
            wider, namespace="witness", target="head", expected_generation=1
        )
        acquire_run_lease(
            store, first.run_id, kind="session", lease_id="s-1", ttl_seconds=600
        )
        retain_run(store, second.run_id)
        receipt = run_gc([RunStoreGcJob(store=store, retain_history=1)])
        survivor = store.project_run(second.run_id)
    return receipt, survivor


def test_the_observer_writes_telemetry_and_changes_no_sweep_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The distinguishing witness: with the observer off and on, the same
    story yields the same receipts, the same surviving bytes, and
    byte-identical store contents — the observation never becomes a hidden
    consumer holding objects back from collection.  The lease clock is
    frozen so the two halves differ in exactly one thing: the observer."""
    monkeypatch.setattr(store_module, "_lease_now", lambda: 4_000_000)
    dark = tmp_path / "dark"
    lit = tmp_path / "lit"

    bootstrap(ObservabilityConfig(enabled=False))
    try:
        dark_receipt, dark_survivor = _sweep_story(dark)
    finally:
        shutdown()
    assert not (dark / ".codeclone").exists()

    bootstrap(ObservabilityConfig(enabled=True), root=lit)
    try:
        with operation(name="mcp.analyze_repository", surface="mcp"):
            lit_receipt, lit_survivor = _sweep_story(lit)
    finally:
        shutdown()

    assert lit_receipt == dark_receipt
    assert lit_survivor == dark_survivor
    assert _store_contents(lit / "runs.sqlite") == _store_contents(dark / "runs.sqlite")
    assert len(_span_rows(lit, "gc.collect")) == 1


# -- the protocol is real: two production surfaces in one dispatch -----------


@dataclass
class _ObservabilityRetentionGcJob:
    """The observability store's age retention as a job, wrapping the REAL
    ``run_retention_gc``: the hold predicate is a time window over
    operations — the ``history`` reason, time-based instead of
    count-based."""

    connection: sqlite3.Connection
    retention_days: int
    name: str = field(default="platform_observability", init=False)

    def collect(self) -> GcJobReport:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM platform_operations"
        ).fetchone()
        candidates = int(row[0]) if row else 0
        deleted = run_retention_gc(self.connection, retention_days=self.retention_days)
        return GcJobReport.build(
            job=self.name,
            candidates=candidates,
            held={GC_HOLD_HISTORY: candidates - deleted},
            collected={GC_COLLECT_EXPIRED: deleted},
        )


def _operation_record(operation_id: str, started_at_utc: str) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
        correlation_id="corr-1",
        surface="mcp",
        name="finish_controlled_change",
        started_at_utc=started_at_utc,
        duration_ms=1.0,
        status="ok",
        parent_operation_id=None,
        spans=(),
    )


def test_the_protocol_holds_two_production_surfaces_in_one_dispatch(
    tmp_path: Path,
) -> None:
    """The maintainer's reality check, in this ring: the observability
    retention collector that already lived in the tree becomes a job of
    this orchestrator next to the run-store job, in one dispatch, with
    honest per-surface accounting — no protocol bending, no surface
    knowledge in the orchestrator.  (The workspace-intent collector passes
    the same check in its own ring: tests/test_gc_workspace_intent_job.py.)
    """
    run_store = RunStore(tmp_path / "runs.sqlite")
    first = run_store.write_full_run(
        fixture_model(), namespace="pair", target="head", expected_generation=0
    )
    model = fixture_model()
    wider = replace(
        model,
        coupled_sets=frozenset(set(model.coupled_sets) | {frozenset({"Wide"})}),
    )
    run_store.write_full_run(
        wider, namespace="pair", target="head", expected_generation=1
    )

    observability = open_observability_store(observability_store_path(tmp_path))
    write_operation(observability, _operation_record("op-old", "2026-06-09T00:00:00Z"))
    now_text = (datetime.now(timezone.utc).replace(microsecond=0).isoformat()).replace(
        "+00:00", "Z"
    )
    write_operation(observability, _operation_record("op-young", now_text))

    try:
        receipt = run_gc(
            [
                _ObservabilityRetentionGcJob(
                    connection=observability, retention_days=14
                ),
                RunStoreGcJob(store=run_store, retain_history=0),
            ]
        )
    finally:
        observability.close()
        run_store.close()

    assert [report.job for report in receipt.reports] == [
        "canonical_run_store",
        "platform_observability",
    ]
    by_job = {report.job: report for report in receipt.reports}

    swept = by_job["canonical_run_store"]
    assert swept.collected_count(GC_COLLECT_UNREACHABLE) == 1
    assert swept.held_count(GC_HOLD_HEAD) == 1

    retention = by_job["platform_observability"]
    assert retention.candidates == 2
    assert retention.held_count(GC_HOLD_HISTORY) == 1
    assert retention.collected_count(GC_COLLECT_EXPIRED) == 1

    with RunStore(tmp_path / "runs.sqlite") as reopened, pytest.raises(UnknownRunError):
        reopened.read_run(first.run_id)
