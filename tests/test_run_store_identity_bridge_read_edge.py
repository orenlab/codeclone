# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The production read edge of the identity bridge.

The process that published a run holds the relation in RAM: its record's
``run_snapshot_link`` names the store run.  Every OTHER process holds only
the report half -- the evaluated identity, and the scope receipt its own
document re-derives -- and until this edge existed it could not address the
persisted snapshot at all: the store's index (``run_report_links``) was
written on every publication and read by nothing in production (serving
census 2, §3 and §14.6).

Pinned here, each with its own mutation target:

* a NEW process -- a separate interpreter publishes, this one never sees its
  RAM -- finds exactly the persisted snapshot behind its report identity and
  serves it, with provenance that says the path was the bridge;
* an edge that addresses a run over another scope (wrong), two edges for one
  identity (ambiguous) and no edge (missing) each fail closed with a reason
  the door's vocabulary already has, and the refusal touches no store byte;
* no session-local fallback and no lookup "by something similar": with the
  edge gone and exactly one run over the same scope still in the store, the
  door says the run is not published;
* the bridge lane is ONE store resolution and ONE store open per request,
  both measured on class objects (wave A's meter and its sibling here).

Everything below reaches the engine through the r3 door and the r4 surface
only; the store is built by real publications in child interpreters and
inspected with the standard library, never through the r2 modules.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from codeclone.api import run_store_serving as door_mod
from codeclone.api.run_store_serving import (
    MEMORY_BY_DESIGN_REASONS,
    SERVING_REASON_INTEGRITY,
    SERVING_REASON_NOT_PUBLISHED,
    SERVING_REASON_RUN_NOT_PUBLISHED,
    SERVING_REASON_SERVED,
    SERVING_REASON_STORE_ABSENT,
    SERVING_SOURCE_MEMORY,
    SERVING_SOURCE_RUN_STORE,
    RunStoreServingOutcome,
    read_run_store_slices,
)
from codeclone.surfaces.mcp import _run_store_serving as run_store_serving_mod
from codeclone.surfaces.mcp._session_shared import (
    MCPAnalysisRequest,
    MCPRunNotFoundError,
    MCPRunRecord,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests.test_implementation_context_run_store_serving import (
    _enable_store,
    _MechanismMeter,
    _write_two_file_corpus,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROLLOUT_KEYS = (
    "CODECLONE_RUN_STORE_ENABLED",
    "CODECLONE_RUN_STORE_FORCE",
    "CODECLONE_RUN_STORE_PATH",
)
#: The provenance a bridge-served answer carries in ``serving.detail``: the
#: published payload value, pinned as the literal the payload shows.
_BRIDGE_DETAIL = "identity_bridge"
#: The link's contract words, as the model spells them (``codeclone.models``
#: is an r2 module this test may not import; the spelling is the contract).
_LINK_UNPUBLISHED = "unpublished"
_OUTCOME_DISABLED = "disabled"
_REQUEST = {"paths": ["pkg/callee.py"], "include": ["callers"]}

#: Process A.  A separate interpreter publishes a corpus into the store and
#: reports what its RAM held; nothing of it survives into this process.
_PUBLISHER_CHILD = """
import json, os, sys
import codeclone
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
from codeclone.surfaces.mcp.service import CodeCloneMCPService

service = CodeCloneMCPService(history_limit=2)
service.analyze_repository(
    MCPAnalysisRequest(
        root=sys.argv[1], respect_pyproject=False, min_loc=1, min_stmt=1
    )
)
record = service._runs.resolve_any_root()
link = record.execution.run_snapshot_link
print(json.dumps({
    "pid": os.getpid(),
    "engine": codeclone.__file__,
    "run_id": record.run_id,
    "execution_event_id": record.execution.execution_event_id,
    "link": None if link is None else {
        "state": link.state,
        "outcome": link.outcome,
        "store_run_id": link.store_run_id,
        "analysis_scope_digest": link.analysis_scope_digest,
        "report_run_identity": link.report_run_identity,
    },
}))
"""


@dataclass(frozen=True)
class _Publication:
    """What one child interpreter reported about its own publication."""

    pid: int
    run_id: str
    execution_event_id: str
    store_run_id: str
    analysis_scope_digest: str


@dataclass(frozen=True)
class _Publisher:
    root: Path
    store: Path
    #: The corpus every pin below asks about.
    main: _Publication
    #: A second corpus over ANOTHER scope, published into the same store: the
    #: foreign run a corrupted index is pointed at.
    foreign: _Publication


def _publish_in_a_child(root: Path, store: Path) -> _Publication:
    env = {k: v for k, v in os.environ.items() if k not in _ROLLOUT_KEYS}
    env.update(
        {
            "CODECLONE_RUN_STORE_ENABLED": "1",
            "CODECLONE_RUN_STORE_FORCE": "1",
            "CODECLONE_RUN_STORE_PATH": str(store),
        }
    )
    completed = subprocess.run(
        (sys.executable, "-c", _PUBLISHER_CHILD, str(root)),
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    witness = json.loads(completed.stdout)
    # Execution provenance, asserted rather than assumed: another pid, THIS
    # tree's engine, and a RAM link that was ``linked`` with a store address
    # -- the half this process will never hold.
    assert witness["pid"] != os.getpid(), "the publisher must be another interpreter"
    assert Path(witness["engine"]).resolve().is_relative_to(_REPO_ROOT), witness
    link = witness["link"]
    assert link is not None and link["state"] == "linked" and link["store_run_id"]
    return _Publication(
        pid=int(witness["pid"]),
        run_id=str(witness["run_id"]),
        execution_event_id=str(witness["execution_event_id"]),
        store_run_id=str(link["store_run_id"]),
        analysis_scope_digest=str(link["analysis_scope_digest"]),
    )


@pytest.fixture(scope="module")
def publisher(tmp_path_factory: pytest.TempPathFactory) -> _Publisher:
    """Process A: two publications by child interpreters, one store."""
    base = tmp_path_factory.mktemp("bridge-read-edge")
    store = base / "published.sqlite3"
    root = base / "src"
    _write_two_file_corpus(root)
    foreign_root = base / "foreign"
    _write_two_file_corpus(foreign_root)
    (foreign_root / "pkg" / "second.py").write_text(
        "def second() -> int:\n    return 22\n", "utf-8"
    )
    main = _publish_in_a_child(root, store)
    foreign = _publish_in_a_child(foreign_root, store)
    assert main.run_id != foreign.run_id
    assert main.analysis_scope_digest != foreign.analysis_scope_digest
    assert store.exists()
    assert not store.with_name(store.name + "-wal").exists(), "A closed its store"
    return _Publisher(root=root, store=store, main=main, foreign=foreign)


def _store_copy(publisher: _Publisher, tmp_path: Path) -> Path:
    """One test, one private copy of what process A published."""
    copy = tmp_path / "runs.sqlite3"
    shutil.copy(publisher.store, copy)
    return copy


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: SQLite's own bookkeeping in the 100-byte file header: the file change
#: counter (24..28) and the version-valid-for number (92..96).  Measured
#: 2026-09-19: opening a store through ``RunStore`` moves exactly these two
#: fields (the open-time witness handshake commits an immediate transaction)
#: and no other byte -- on every open, the publication lane's included.  A
#: pure read is therefore "no byte outside those two fields", pinned below
#: beside "no row of any table".
_SQLITE_COUNTER_FIELDS = ((24, 28), (92, 96))
_STORE_TABLES = (
    "store_meta",
    "witness",
    "namespaces",
    "objects",
    "runs",
    "run_members",
    "heads",
    "head_history",
    "run_leases",
    "retained_runs",
    "run_report_links",
)


def _bytes_outside_sqlite_counters(path: Path) -> bytes:
    raw = bytearray(path.read_bytes())
    for start, end in _SQLITE_COUNTER_FIELDS:
        raw[start:end] = b"\0" * (end - start)
    return bytes(raw)


def _query(path: Path, statement: str, *parameters: object) -> list[tuple[Any, ...]]:
    """A read-only look at the store (proven not to move a byte: a raw
    ``mode=ro`` read leaves the file identical)."""
    raw = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return raw.execute(statement, parameters).fetchall()
    finally:
        raw.close()


def _store_rows(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, as a read-only snapshot."""
    return {
        table: _query(path, f"SELECT * FROM {table} ORDER BY 1")
        for table in _STORE_TABLES
    }


def _run_pk(path: Path, run_id: str) -> int:
    rows = _query(path, "SELECT run_pk FROM runs WHERE run_id = ?", run_id)
    assert len(rows) == 1, rows
    return int(rows[0][0])


def _edit_index(store: Path, statement: str, *parameters: object) -> None:
    raw = sqlite3.connect(store)
    try:
        with raw:
            raw.execute(statement, parameters)
    finally:
        raw.close()


def _new_process(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[CodeCloneMCPService, MCPRunRecord]:
    """Process B: a service that never held A's RAM, analysed with the
    rollout OFF, so its own record carries no store address."""
    for key in _ROLLOUT_KEYS:
        monkeypatch.delenv(key, raising=False)
    service = CodeCloneMCPService(history_limit=2)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(root), respect_pyproject=False, min_loc=1, min_stmt=1
        )
    )
    return service, service._runs.resolve_any_root()


def _report_half(record: MCPRunRecord, publisher: _Publisher) -> Any:
    """B's link: the report half only, proven before anything is served.

    Probe validity, not decoration: a record that already named the store
    run would make every bridge pin below hollow, served by RAM.
    """
    link = record.execution.run_snapshot_link
    assert link is not None
    assert link.state == _LINK_UNPUBLISHED, link
    assert link.store_run_id == "", "B's record must not name a store run"
    assert record.run_id == publisher.main.run_id, (
        "INCONCLUSIVE: the two processes evaluated different report identities"
    )
    assert link.report_run_identity == record.run_id
    return link


def _bridge_subject(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, CodeCloneMCPService, MCPRunRecord]:
    """Process B over a private copy of A's store, proven to hold the report
    half of the relation and nothing more."""
    store = _store_copy(publisher, tmp_path)
    service, record = _new_process(publisher.root, monkeypatch)
    _report_half(record, publisher)
    return store, service, record


class _StoreOpenMeter:
    """Every ``RunStore`` construction, counted on the class object.

    The sibling of wave A's ``_MechanismMeter``: one is the number of
    outcomes minted, this is the number of stores opened.  A bridge lane
    that resolved the edge on one handle and read the slices on another
    would still mint one outcome, so the outcome meter alone cannot see
    the second open -- and a run swept between the two opens would turn a
    verified edge into a wrong answer mid-request.  The class is reached as
    the door itself binds it, so the count is the door's own store.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.opens = 0
        # Read out of the door's own namespace mapping: the name is the
        # store class the door binds at import, not an export of the door
        # (the same reading wave A uses for the consumer's re-import).
        store_class = vars(door_mod)["RunStore"]
        real = store_class.__init__

        def counting(inner: Any, *args: Any, **kwargs: Any) -> None:
            self.opens += 1
            real(inner, *args, **kwargs)

        monkeypatch.setattr(store_class, "__init__", counting)


def _served_over_the_bridge(store_run_id: str) -> dict[str, object]:
    return {
        "source": SERVING_SOURCE_RUN_STORE,
        "reason": SERVING_REASON_SERVED,
        "store_run_id": store_run_id,
        "detail": _BRIDGE_DETAIL,
    }


# ---------------------------------------------------------------------------
# Acceptance: A publishes; B, without A's RAM, serves A's snapshot.
# ---------------------------------------------------------------------------


def test_the_unpublished_link_carries_the_report_half_of_the_relation(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B's record carries what a bridge needs and nothing a bridge gave it.

    The scope receipt B re-derives from its own document equals the receipt
    A's store row carries: the witness two processes will compare is one
    value computed by one owner on both sides.  B's analysis wrote nothing
    into the store, byte for byte.
    """
    store, _service, record = _bridge_subject(publisher, tmp_path, monkeypatch)
    link = record.execution.run_snapshot_link
    assert link is not None
    assert link.outcome == _OUTCOME_DISABLED
    assert link.analysis_scope_digest == publisher.main.analysis_scope_digest
    assert _file_digest(store) == _file_digest(publisher.store), (
        "B's analysis must not touch the store"
    )


def test_a_new_process_serves_the_snapshot_another_process_published(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The edge: B holds the report identity, the store's index answers it.

    Every shape that serves slices -- the explicit ``paths`` shape and the
    ``query`` search -- comes back store-backed, naming A's store run and
    saying the path was the bridge; the resolution is one outcome and one
    store open; and serving is a pure read of the store.
    """
    store, service, _record = _bridge_subject(publisher, tmp_path, monkeypatch)
    with pytest.raises(MCPRunNotFoundError):
        service._runs.get_execution(publisher.main.execution_event_id)
    rows_before = _store_rows(store)
    bytes_before = _bytes_outside_sqlite_counters(store)

    _enable_store(monkeypatch, store=store)
    outcomes = _MechanismMeter(monkeypatch)
    opens = _StoreOpenMeter(monkeypatch)
    answer = service.get_implementation_context(root=str(publisher.root), **_REQUEST)
    assert answer["status"] == "ok"
    assert answer["serving"] == _served_over_the_bridge(publisher.main.store_run_id)
    assert outcomes.reasons == [SERVING_REASON_SERVED]
    assert opens.opens == 1, "the bridge lane opens the store once per request"
    call_context = answer["call_context"]
    assert isinstance(call_context, dict) and call_context["callers"]

    outcomes.reset()
    searched = service.get_implementation_context(
        root=str(publisher.root), query="target"
    )
    assert searched["serving"] == _served_over_the_bridge(publisher.main.store_run_id)
    assert outcomes.reasons == [SERVING_REASON_SERVED]
    assert opens.opens == 2

    assert _store_rows(store) == rows_before
    assert _bytes_outside_sqlite_counters(store) == bytes_before, (
        "serving is a pure read: no byte outside SQLite's own header counters"
    )
    assert door_mod.SERVING_DETAIL_IDENTITY_BRIDGE == _BRIDGE_DETAIL


def test_a_record_that_published_takes_the_publication_lane_not_the_bridge(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bridge is the road for a record WITHOUT a store address.

    A record whose own execution published carries the address in RAM and
    is served through it -- the provenance block wave A pinned, with no
    ``detail`` -- so the index is never consulted for a relation the
    process already holds.
    """
    store = _store_copy(publisher, tmp_path)
    _enable_store(monkeypatch, store=store)
    service = CodeCloneMCPService(history_limit=2)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(publisher.root), respect_pyproject=False, min_loc=1, min_stmt=1
        )
    )
    record = service._runs.resolve_any_root()
    link = record.execution.run_snapshot_link
    assert link is not None and link.store_run_id, link
    answer = service.get_implementation_context(root=str(publisher.root), **_REQUEST)
    assert answer["serving"] == {
        "source": SERVING_SOURCE_RUN_STORE,
        "reason": SERVING_REASON_SERVED,
        "store_run_id": link.store_run_id,
    }


# ---------------------------------------------------------------------------
# Fail closed: wrong, ambiguous, missing -- typed, and the store untouched.
# ---------------------------------------------------------------------------


def _refused(
    service: CodeCloneMCPService, publisher: _Publisher, store: Path
) -> dict[str, object]:
    """Serve through the corrupted index; prove the refusal wrote nothing."""
    rows_before = _store_rows(store)
    bytes_before = _bytes_outside_sqlite_counters(store)
    answer = service.get_implementation_context(root=str(publisher.root), **_REQUEST)
    assert answer["status"] == "ok"
    assert _store_rows(store) == rows_before, "a refusal touches no store row"
    assert _bytes_outside_sqlite_counters(store) == bytes_before
    serving = answer["serving"]
    assert isinstance(serving, dict)
    assert serving["source"] == SERVING_SOURCE_MEMORY
    assert serving["reason"] not in MEMORY_BY_DESIGN_REASONS, "a fallback, counted"
    call_context = answer["call_context"]
    assert isinstance(call_context, dict) and call_context["callers"], (
        "memory answers when the store cannot"
    )
    return serving


def test_a_wrong_edge_is_refused_closed(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The edge names a run over another scope: the witness disagrees.

    Both endpoints would verify -- the foreign run against its own
    membership, B's document against its own integrity block -- and only
    the relation is false.  The door refuses before reading one family.
    """
    store, service, record = _bridge_subject(publisher, tmp_path, monkeypatch)
    _edit_index(
        store,
        "UPDATE run_report_links SET run_pk = ? WHERE report_run_identity = ?",
        _run_pk(store, publisher.foreign.store_run_id),
        record.run_id,
    )
    _enable_store(monkeypatch, store=store)
    serving = _refused(service, publisher, store)
    assert serving["reason"] == SERVING_REASON_INTEGRITY
    assert "store_run_id" not in serving
    assert "scope" in str(serving["detail"])


def test_a_substituted_receipt_on_the_report_half_is_refused_closed(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of the same witness: the edge is right, the holder's
    receipt is not.  Refused at the door, before any family is read."""
    store, _service, record = _bridge_subject(publisher, tmp_path, monkeypatch)
    link = record.execution.run_snapshot_link
    assert link is not None
    _enable_store(monkeypatch, store=store)
    opens = _StoreOpenMeter(monkeypatch)
    slices, outcome = read_run_store_slices(
        root=record.root, link=replace(link, analysis_scope_digest="f" * 64)
    )
    assert slices is None
    assert (outcome.source, outcome.reason) == (
        SERVING_SOURCE_MEMORY,
        SERVING_REASON_INTEGRITY,
    )
    assert outcome.store_run_id == ""
    assert "scope" in outcome.detail
    assert opens.opens == 1


def test_two_edges_for_one_identity_are_refused_closed(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One evaluation cannot descend from two analyses; the first is not taken."""
    store, service, record = _bridge_subject(publisher, tmp_path, monkeypatch)
    _edit_index(
        store,
        "INSERT INTO run_report_links (report_run_identity, run_pk) VALUES (?, ?)",
        record.run_id,
        _run_pk(store, publisher.foreign.store_run_id),
    )
    _enable_store(monkeypatch, store=store)
    serving = _refused(service, publisher, store)
    assert serving["reason"] == SERVING_REASON_INTEGRITY
    assert "store_run_id" not in serving
    assert "linked to 2 analysis runs" in str(serving["detail"])


def test_a_missing_edge_is_not_recovered_by_scope_similarity(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No edge, and exactly ONE published run over B's scope: still refused.

    The library's recomputed lane would answer this store with that lone
    candidate; the production edge must not, because the scope receipt is
    a compatibility witness and never the key -- one scope carries many
    snapshots, and the one left is not thereby the one behind THIS document.
    """
    store, service, record = _bridge_subject(publisher, tmp_path, monkeypatch)
    _edit_index(
        store,
        "DELETE FROM run_report_links WHERE report_run_identity = ?",
        record.run_id,
    )
    candidates = _query(
        store,
        "SELECT run_id FROM runs WHERE analysis_scope_digest = ? AND published = 1",
        publisher.main.analysis_scope_digest,
    )
    assert candidates == [(publisher.main.store_run_id,)], "the lone candidate exists"
    _enable_store(monkeypatch, store=store)
    serving = _refused(service, publisher, store)
    assert serving["reason"] == SERVING_REASON_RUN_NOT_PUBLISHED
    assert "store_run_id" not in serving
    assert record.run_id[:12] in str(serving["detail"])


def test_a_report_nobody_published_is_run_not_published(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store that holds runs, none of which answers this document."""
    store = _store_copy(publisher, tmp_path)
    root = tmp_path / "other"
    _write_two_file_corpus(root)
    (root / "pkg" / "extra.py").write_text(
        "def more() -> int:\n    return 2\n", "utf-8"
    )
    service, record = _new_process(root, monkeypatch)
    link = record.execution.run_snapshot_link
    assert link is not None and link.store_run_id == ""
    assert record.run_id not in {publisher.main.run_id, publisher.foreign.run_id}
    _enable_store(monkeypatch, store=store)
    rows_before = _store_rows(store)
    answer = service.get_implementation_context(root=str(root), **_REQUEST)
    assert answer["serving"] == {
        "source": SERVING_SOURCE_MEMORY,
        "reason": SERVING_REASON_RUN_NOT_PUBLISHED,
        "detail": (
            f"no published run of this store answers report {record.run_id[:12]}"
        ),
    }
    assert _store_rows(store) == rows_before


def test_an_absent_store_is_named_when_only_the_report_half_is_held(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rollout names a store that is not there: typed, and not created."""
    service, record = _new_process(publisher.root, monkeypatch)
    _report_half(record, publisher)
    absent = tmp_path / "nowhere" / "runs.sqlite3"
    _enable_store(monkeypatch, store=absent)
    answer = service.get_implementation_context(root=str(publisher.root), **_REQUEST)
    serving = answer["serving"]
    assert isinstance(serving, dict)
    assert (serving["source"], serving["reason"]) == (
        SERVING_SOURCE_MEMORY,
        SERVING_REASON_STORE_ABSENT,
    )
    assert "store_run_id" not in serving
    assert not absent.exists() and not absent.parent.exists()


# ---------------------------------------------------------------------------
# Memory by design stays memory by design.
# ---------------------------------------------------------------------------


def test_the_report_half_stays_memory_by_design_while_the_rollout_is_off(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody reads a store the rollout does not name -- the bridge included."""
    _service, record = _new_process(publisher.root, monkeypatch)
    link = _report_half(record, publisher)
    opens = _StoreOpenMeter(monkeypatch)
    slices, outcome = read_run_store_slices(root=record.root, link=link)
    assert slices is None
    assert (outcome.reason, outcome.detail) == (
        SERVING_REASON_NOT_PUBLISHED,
        _OUTCOME_DISABLED,
    )
    assert opens.opens == 0


def test_a_record_with_no_bridge_at_all_is_memory_by_design(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``None`` is "no bridge was stated", not "look it up by nothing"."""
    store = _store_copy(publisher, tmp_path)
    _enable_store(monkeypatch, store=store)
    opens = _StoreOpenMeter(monkeypatch)
    slices, outcome = read_run_store_slices(root=publisher.root, link=None)
    assert slices is None
    assert (outcome.reason, outcome.detail) == (SERVING_REASON_NOT_PUBLISHED, "")
    assert opens.opens == 0


def test_the_resolver_compares_a_bridged_answer_with_memory(
    publisher: _Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shadow comparison guards the bridge lane exactly as it guards the
    publication lane: a bridged answer that disagrees with memory is not
    served, and memory wins with ``divergent``."""
    store, _service, record = _bridge_subject(publisher, tmp_path, monkeypatch)
    _enable_store(monkeypatch, store=store)
    stored, outcome = run_store_serving_mod.served_slices(record)
    assert outcome.as_payload() == _served_over_the_bridge(publisher.main.store_run_id)
    disagreeing = replace(stored, unit_inventory=())

    def diverging_door(
        *, root: Path, link: object
    ) -> tuple[object, RunStoreServingOutcome]:
        return disagreeing, RunStoreServingOutcome(
            source=SERVING_SOURCE_RUN_STORE,
            reason=SERVING_REASON_SERVED,
            store_run_id=publisher.main.store_run_id,
            detail=_BRIDGE_DETAIL,
        )

    monkeypatch.setattr(run_store_serving_mod, "read_run_store_slices", diverging_door)
    served, verdict = run_store_serving_mod.served_slices(record)
    assert served.unit_inventory, "memory wins the argument"
    assert verdict.as_payload() == {
        "source": SERVING_SOURCE_MEMORY,
        "reason": "divergent",
        "store_run_id": publisher.main.store_run_id,
        "detail": _BRIDGE_DETAIL,
    }
