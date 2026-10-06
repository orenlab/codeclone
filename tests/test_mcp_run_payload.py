# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A held run is split into a resident identity and a droppable payload.

Held here:

* the registry -- a dropped payload keeps the run's place, ordinal, pins
  and index entry; the record resolvers refuse it typed, the ``held_*``
  ones answer its identity; the history limit counts payloads and the
  resident limit identities, each oldest first;
* the session's side of it on a temporary repository with its own store
  (the rollout and the serving switch set inside the test, never a
  production store): which payloads go, oldest first, and which stay;
* the state a run carries outlives its payload, and an intent whose
  before-run lost only its payload is not retired.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, fields, replace
from pathlib import Path

import pytest

from codeclone.api.execution_event import ExecutionEvent
from codeclone.api.run_residence import ResidentRun, RunSummaryResidue
from codeclone.api.run_store_serving import prove_published_run
from codeclone.api.served_projection import build_served_projection
from codeclone.surfaces.mcp._run_residence import resident_identity
from codeclone.surfaces.mcp._session_shared import (
    MCP_RESIDENT_HISTORY_LIMIT,
    RESIDENT_RECORD_FIELDS,
    CodeCloneMCPRunStore,
    MCPAnalysisRequest,
    MCPRunIdentity,
    MCPRunNotFoundError,
    MCPRunPayloadEvictedError,
    MCPRunRecord,
    mint_execution_event_id,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping


def _record(root: Path, run_id: str) -> MCPRunRecord:
    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        served_report=build_served_projection({}),
        summary={"run_id": run_id},
        changed_paths=(),
        changed_projection=None,
        func_clones_count=0,
        block_clones_count=0,
        reachable_qualnames=frozenset(),
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
        execution=ExecutionEvent(
            execution_event_id=mint_execution_event_id(),
            root=root,
            semantic_report_id=run_id,
        ),
    )


def _identity(record: MCPRunRecord) -> MCPRunIdentity:
    return MCPRunIdentity(
        **{name: getattr(record, name) for name in RESIDENT_RECORD_FIELDS},
        summary_residue=RunSummaryResidue(
            version="v",
            schema="s",
            cache={},
            baseline_execution={},
            entity_counts=None,
            security_presentation={},
        ),
    )


def _event(record: MCPRunRecord | MCPRunIdentity) -> str:
    return record.execution.execution_event_id


def _held_runs(
    store: CodeCloneMCPRunStore,
) -> tuple[MCPRunRecord | MCPRunIdentity, ...]:
    with store._lock:
        return tuple(store._executions.values())


# ── the registry ─────────────────────────────────────────────────────────


def test_the_resident_fields_and_the_payload_split_the_record() -> None:
    """Every record field is in exactly one part: resident by name, or the
    payload; the identity takes the resident ones and adds only what it
    copies out of the payload."""
    record_fields = [field.name for field in fields(MCPRunRecord)]
    identity_fields = [field.name for field in fields(ResidentRun)]
    assert set(RESIDENT_RECORD_FIELDS) < set(record_fields)
    assert identity_fields[: len(RESIDENT_RECORD_FIELDS)] == list(
        RESIDENT_RECORD_FIELDS
    )
    assert identity_fields[len(RESIDENT_RECORD_FIELDS) :] == ["summary_residue"]
    assert sorted(set(record_fields) - set(RESIDENT_RECORD_FIELDS)) == [
        "changed_projection",
        "coverage_join",
        "metrics_diff",
        "module_imports",
        "new_block",
        "new_func",
        "reachable_qualnames",
        "relationship_facts",
        "served_report",
        "suggestions",
        "summary",
        "unit_inventory",
    ]


def test_a_dropped_payload_keeps_the_runs_place_ordinal_pins_and_name(
    tmp_path: Path,
) -> None:
    store = CodeCloneMCPRunStore(history_limit=4)
    first = store.register(_record(tmp_path, "a" * 64))
    second = store.register(_record(tmp_path, "b" * 64))
    store.pin_execution(_event(first))
    ordinal = store.execution_ordinal(_event(first))

    assert store.drop_payload(_identity(first)) is True

    held = store.held_execution(_event(first))
    assert isinstance(held, ResidentRun)
    assert held.execution is first.execution
    assert store.held_for_root("a" * 8, root=tmp_path) == held
    assert store.held_any_root("a" * 64) == held
    assert store.holds_execution(_event(first))
    assert store.execution_ordinal(_event(first)) == ordinal
    assert store.pin_count(_event(first)) == 1
    assert store.records() == (second,)
    assert _held_runs(store) == (held, second)
    assert store.held_run_ids() == frozenset({"a" * 64, "b" * 64})
    resolvers: tuple[Callable[[], MCPRunRecord], ...] = (
        lambda: store.get_execution(_event(first)),
        lambda: store.get_for_root("a" * 64, root=tmp_path),
        lambda: store.resolve_any_root("a" * 64),
    )
    for resolve in resolvers:
        with pytest.raises(MCPRunPayloadEvictedError) as refused:
            resolve()
        assert refused.value.identity == held


def test_a_payload_is_dropped_once_and_only_by_its_own_identity(
    tmp_path: Path,
) -> None:
    store = CodeCloneMCPRunStore(history_limit=4)
    first = store.register(_record(tmp_path, "a" * 64))
    other = _record(tmp_path, "b" * 64)
    impostor = replace(_identity(other), execution=first.execution)

    with pytest.raises(ValueError, match="only the record it was taken from"):
        store.drop_payload(impostor)
    assert store.drop_payload(_identity(other)) is False
    assert store.drop_payload(_identity(first)) is True
    assert store.drop_payload(_identity(first)) is False
    # Only the producer registering the execution again brings a record back.
    store.register(first)
    assert store.get_execution(_event(first)) is first


def test_the_history_limit_counts_payloads_and_the_resident_limit_identities(
    tmp_path: Path,
) -> None:
    store = CodeCloneMCPRunStore(history_limit=2)
    resident = [store.register(_record(tmp_path, f"{n:064d}")) for n in range(3)]
    # Three whole, unpinned, limit two: the oldest went whole, as always.
    assert [_event(run) for run in _held_runs(store)] == [
        _event(run) for run in resident[1:]
    ]
    for run in resident[1:]:
        store.drop_payload(_identity(run))
    whole = [store.register(_record(tmp_path, f"{n:064d}")) for n in range(3, 5)]

    # Two identities and two payloads: neither bound is reached.
    assert store.records() == tuple(whole)
    assert len(_held_runs(store)) == 4


def test_the_resident_limit_forgets_the_oldest_unpinned_identity(
    tmp_path: Path,
) -> None:
    store = CodeCloneMCPRunStore(history_limit=2)
    pinned = store.register(_record(tmp_path, "p" * 64))
    store.pin_execution(_event(pinned))
    store.drop_payload(_identity(pinned))
    identities = []
    for n in range(MCP_RESIDENT_HISTORY_LIMIT + 1):
        run = store.register(_record(tmp_path, f"{n:064d}"))
        store.drop_payload(_identity(run))
        identities.append(run)
    store.register(_record(tmp_path, "z" * 64))

    held = [_event(run) for run in _held_runs(store)]
    # The oldest unpinned identity went; the pinned one, older still, stayed.
    assert _event(identities[0]) not in held
    assert held[:2] == [_event(pinned), _event(identities[1])]
    assert len(held) == 1 + MCP_RESIDENT_HISTORY_LIMIT + 1


def test_the_resident_limit_is_its_policy_value() -> None:
    """A policy bound, like the pin ceiling: no derivation to re-run, so its
    value is held here and a change to it is a decision, not a drift."""
    assert MCP_RESIDENT_HISTORY_LIMIT == 32


# ── the session's side, on a temporary repository with its own store ────


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e.com",
        },
    )


@dataclass
class _Session:
    root: Path
    store: Path
    service: CodeCloneMCPService

    def analyze(self, functions: int) -> MCPRunRecord:
        body = "".join(
            f"def f{n}(x: int) -> int:\n    return x * {n}\n\n"
            for n in range(functions)
        )
        self.root.joinpath("pkg", "m.py").write_text(body, "utf-8")
        self.service.analyze_repository(
            MCPAnalysisRequest(root=str(self.root), respect_pyproject=False)
        )
        return self.service._runs.records()[-1]

    def held(self, record: MCPRunRecord) -> MCPRunRecord | MCPRunIdentity:
        return self.service._runs.held_execution(_event(record))


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Session]:
    root = tmp_path / "repo"
    root.joinpath("pkg").mkdir(parents=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    store = tmp_path / "runs.sqlite3"
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store))
    monkeypatch.setenv("CODECLONE_SERVE_FROM", "run_store")
    root.joinpath("pkg", "m.py").write_text("", "utf-8")
    root.joinpath("README.md").write_text("stable\n", "utf-8")
    for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "init")):
        _git(root, *args)
    yield _Session(root=root, store=store, service=CodeCloneMCPService(history_limit=2))


def _start(session: _Session, path: str = "README.md") -> str:
    started = session.service.start_controlled_change(
        root=str(session.root),
        scope={"allowed_files": [path]},
        intent=f"edit {path}",
    )
    assert started["status"] == "active", started
    return str(started["intent_id"])


def test_the_oldest_droppable_payload_goes_and_room_is_left_for_one(
    session: _Session,
) -> None:
    first = session.analyze(1)
    second = session.analyze(2)

    dropped = session.service._relieve_payload_pressure(incoming=1)

    assert dropped == (_event(first),)
    assert session.held(first) == resident_identity(first)
    assert session.held(second) is second


def test_no_payload_goes_while_the_limit_holds(session: _Session) -> None:
    first = session.analyze(1)

    assert session.service._relieve_payload_pressure(incoming=1) == ()
    assert session.held(first) is first


def test_an_unpublished_run_keeps_its_payload(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "0")
    first = session.analyze(1)
    session.analyze(2)
    assert first.execution.run_snapshot_link is not None
    assert first.execution.run_snapshot_link.state == "unpublished"

    assert session.service._relieve_payload_pressure(incoming=1) == ()
    assert session.held(first) is first


def test_with_the_switch_on_memory_every_payload_stays(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = session.analyze(1)
    session.analyze(2)
    monkeypatch.setenv("CODECLONE_SERVE_FROM", "memory")

    assert session.service._relieve_payload_pressure(incoming=1) == ()
    assert session.held(first) is first


def test_a_run_the_store_cannot_prove_keeps_its_payload(session: _Session) -> None:
    first = session.analyze(1)
    session.analyze(2)
    session.store.unlink()

    assert session.service._relieve_payload_pressure(incoming=1) == ()
    assert session.held(first) is first


def test_a_run_whose_membership_does_not_reproduce_keeps_its_payload(
    session: _Session,
) -> None:
    first = session.analyze(1)
    second = session.analyze(2)
    link = first.execution.run_snapshot_link
    assert link is not None
    with sqlite3.connect(session.store) as raw:
        (run_pk,) = raw.execute(
            "SELECT run_pk FROM runs WHERE run_id = ?", (link.store_run_id,)
        ).fetchone()
        raw.execute(
            "DELETE FROM run_members WHERE run_pk = ? AND object_pk = "
            "(SELECT MIN(object_pk) FROM run_members WHERE run_pk = ?)",
            (run_pk, run_pk),
        )

    # Refused ``integrity``: kept, left to the history bound as before, and
    # no newer payload is dropped in its place.
    assert session.service._relieve_payload_pressure(incoming=1) == ()
    assert session.held(first) is first
    assert session.held(second) is second


def test_a_pinned_before_run_goes_only_while_its_intent_holds_the_lease(
    session: _Session,
) -> None:
    before = session.analyze(1)
    intent_id = _start(session)
    newer = session.analyze(2)
    session.service._release_intent_run_leases([intent_id])

    # Pinned, and no lease roots it against the collector: kept, and the
    # next oldest payload the rule lets go goes in its place.
    assert session.service._relieve_payload_pressure(incoming=1) == (_event(newer),)
    assert session.held(before) is before

    session.service._take_intent_run_lease(intent_id=intent_id, record=before)

    assert session.service._relieve_payload_pressure(incoming=2) == (_event(before),)
    assert isinstance(session.held(before), ResidentRun)


def test_the_state_of_a_run_outlives_its_payload(session: _Session) -> None:
    first = session.analyze(1)
    session.analyze(2)
    service = session.service
    service._last_gate_results[first.run_id] = {"exit_code": 0}
    service._relieve_payload_pressure(incoming=1)

    service._prune_session_state()

    assert service._last_gate_results[first.run_id] == {"exit_code": 0}


def test_an_intent_whose_before_run_lost_its_payload_is_not_retired(
    session: _Session,
) -> None:
    session.analyze(1)
    intent_id = _start(session)
    session.analyze(2)
    assert session.service._relieve_payload_pressure(incoming=1)

    session.service._prune_session_state()

    assert intent_id in session.service._active_intents
    assert intent_id not in session.service._before_run_evicted_intents


def test_an_analysis_drops_a_leased_before_run_to_its_identity(
    session: _Session,
) -> None:
    before = session.analyze(1)
    _start(session)
    second = session.analyze(2)
    third = session.analyze(3)

    # Held by identity, not forgotten: the lease keeps its store copy past
    # the collector, so the store can stand in for the payload.
    assert session.held(before) == resident_identity(before)
    assert session.held(second) is second
    assert session.held(third) is third


def test_an_unpinned_run_the_collector_took_is_forgotten_as_before(
    session: _Session,
) -> None:
    first = session.analyze(1)
    # Proven once: the process remembers the proof, never that the run is
    # still published.
    proven = prove_published_run(
        root=first.root, link=first.execution.run_snapshot_link
    )
    assert proven.reason == "served"
    second = session.analyze(2)
    third = session.analyze(3)

    # The third publication collected the first run from the store: nothing
    # can stand in for its payload, so the history bound forgets it, and the
    # newer payloads stay.
    with pytest.raises(MCPRunNotFoundError):
        session.held(first)
    assert session.held(second) is second
    assert session.held(third) is third


def test_an_analysis_never_drops_the_payload_it_registers(session: _Session) -> None:
    first = session.analyze(1)
    first_intent = _start(session, "README.md")
    second = session.analyze(2)
    second_intent = _start(session, "pkg/__init__.py")
    # Both pinned, neither leased: nothing older may go.
    session.service._release_intent_run_leases([first_intent, second_intent])

    third = session.analyze(3)

    assert session.held(first) is first
    assert session.held(second) is second
    assert session.held(third) is third


def test_a_whole_run_the_store_does_not_hold_lends_its_own_facts(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = session.analyze(1)
    # The second run is published to another store: the first is held
    # whole and is not in the store the road now reads.
    monkeypatch.setenv(
        "CODECLONE_RUN_STORE_PATH", str(session.store.with_name("other.sqlite3"))
    )
    second = session.analyze(2)
    ask = {
        "before_run_id": first.run_id,
        "after_run_id": second.run_id,
        "root": str(session.root),
    }
    whole = session.service.compare_runs(**ask)
    session.service._runs.drop_payload(resident_identity(second))

    evicted = session.service.compare_runs(**ask)

    serving = evicted.pop("serving")
    whole.pop("serving")
    assert evicted == whole
    assert isinstance(serving, dict)
    assert serving["runs"]["before"]["reason"] == "run_not_published"
    assert serving["runs"]["after"]["detail"] == "payload_evicted"


def test_an_intent_without_an_execution_binding_resolves_its_run_by_name(
    session: _Session,
) -> None:
    session.analyze(1)
    intent_id = _start(session)
    service = session.service
    intent = service._active_intents[intent_id]
    service._active_intents[intent_id] = replace(intent, before_execution_id=None)
    assert intent.before_execution_id is not None
    service._runs.drop_payload(
        resident_identity(service._runs.get_execution(intent.before_execution_id))
    )

    answer = service.manage_change_intent(action="get", intent_id=intent_id)

    assert answer["intent_id"] == intent_id
    assert answer.get("reason") != "payload_evicted"


def test_a_reader_of_the_intents_payload_is_refused_typed(session: _Session) -> None:
    before = session.analyze(1)
    intent_id = _start(session)
    session.service._runs.drop_payload(resident_identity(before))

    answer = session.service.create_review_receipt(
        intent_id=intent_id, run_id=before.run_id, root=str(session.root)
    )

    assert answer["reason"] == "payload_evicted"
    assert answer["run_id"] == before.run_id[:8]


@pytest.mark.parametrize("action", ["get", "check", "renew"])
def test_an_intent_whose_before_run_lost_its_payload_is_still_managed(
    session: _Session, action: str
) -> None:
    before = session.analyze(1)
    intent_id = _start(session)
    session.service._runs.drop_payload(resident_identity(before))
    extra: dict[str, object] = (
        {"changed_files": ["README.md"]} if action == "check" else {}
    )

    answer = session.service.manage_change_intent(
        action=action, intent_id=intent_id, **extra
    )

    assert answer.get("reason") != "payload_evicted", answer
    assert answer["intent_id"] == intent_id
    # Not expired: the run id the identity keeps is the report digest the
    # intent was declared against.
    assert answer.get("status") != "expired", answer


def test_the_summary_of_a_run_without_its_payload_states_its_drift(
    session: _Session,
) -> None:
    latest = session.analyze(1)
    session.root.joinpath("pkg", "m.py").write_text("# edited\n", "utf-8")
    whole = session.service.get_run_summary(latest.run_id, root=str(session.root))
    session.service._runs.drop_payload(resident_identity(latest))

    evicted = session.service.get_run_summary(latest.run_id, root=str(session.root))

    assert whole["drifted_files"] == ["pkg/m.py"]
    assert evicted["drifted_files"] == whole["drifted_files"]


def test_memory_retrieval_reads_past_a_latest_run_without_payload(
    session: _Session,
) -> None:
    latest = session.analyze(1)
    # The cycle's first retrieval bootstraps the memory store off the run.
    session.service.get_relevant_memory(root=str(session.root), scope=["pkg/m.py"])
    session.service._runs.drop_payload(resident_identity(latest))

    answer = session.service.get_relevant_memory(
        root=str(session.root), scope=["pkg/m.py"]
    )

    assert answer.get("reason") != "payload_evicted", answer
    assert "records" in answer


class _RecordingAuditWriter:
    def __init__(self) -> None:
        self.event_types: list[str] = []

    def emit(self, event: object) -> int:
        self.event_types.append(str(getattr(event, "event_type", "")))
        return len(self.event_types)

    def close(self) -> None:
        return None


def test_a_verification_over_a_before_run_without_payload_writes_its_event(
    session: _Session,
) -> None:
    before = session.analyze(1)
    _git(session.root, "commit", "-qam", "one function")
    intent_id = _start(session, "pkg/m.py")
    after = session.analyze(2)
    audit = _RecordingAuditWriter()
    session.service._audit_writer_override = audit
    session.service._runs.drop_payload(resident_identity(before))

    verified = session.service.check_patch_contract(
        mode="verify",
        intent_id=intent_id,
        after_run_id=after.run_id,
        changed_files=["pkg/m.py"],
        root=str(session.root),
    )

    assert "payload_evicted" in str(as_mapping(verified["serving"]).get("detail"))
    assert verified["status"] == "accepted", verified
    # The answer without a payload is the emitting one, as the whole one was.
    assert audit.event_types.count("patch_contract.verified") == 1
