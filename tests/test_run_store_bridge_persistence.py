# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The identity bridge, persisted: a rebuildable derived index, not a fact.

``ffe371ec`` stated the relation in memory and nowhere else, so every one of
the six MCP server restarts measured on 2026-09-01 threw it away.  This module
measures the persisted edge and the four properties the ruling attaches to it:

1. the stored lane and the recomputed lane name ONE run;
2. emptying the edge table loses nothing -- the relation recomputes;
3. a substituted scope witness is a typed refusal, never a looser match;
4. a real process restart keeps the answer.

The pin the ruling names separately: ``analysis_scope_digest`` is NOT the key
of the relation.  One scope legitimately carries many snapshots -- edit a file
and re-analyze and the paths are unchanged while the facts are not -- so an
edge keyed by the scope receipt would answer "a run over these paths" where
the caller asked "the run behind THIS document".  ``read_run`` re-derives its
run id from the run's own scope and membership, so the wrong-but-real run
verifies perfectly and the falsehood lives only in the relation.  The edge
therefore addresses a concrete immutable row AND a concrete report identity,
and the scope receipt only proves the two are compatible.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.canonical.errors import RunReportLinkError, UnknownRunError
from codeclone.canonical.model import CanonicalModel
from codeclone.canonical.store import (
    RunStore,
    collect_garbage,
    link_run_report,
    linked_run,
    runs_over_scope,
)
from codeclone.core.canonical_snapshot import (
    RunSnapshotBridgeError,
    bridge_run_snapshot,
    persist_run_snapshot_link,
    report_scope_receipt,
    resolve_run_snapshot_link,
)
from codeclone.models import (
    GC_COLLECT_UNREACHABLE,
    RUN_SNAPSHOT_LANE_RECOMPUTED,
    RUN_SNAPSHOT_LANE_STORED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RUN_SNAPSHOT_RESOLUTION_RESOLVED,
    RUN_SNAPSHOT_RESOLUTION_UNLINKED,
    RunSnapshotLink,
    RunSnapshotPublication,
    RunStoreConfig,
)
from tests.test_canonical_roundtrip import fixture_model

_NS = "bridge-persistence"
_TARGET = "probe"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _document(model: CanonicalModel, identity: str) -> dict[str, object]:
    """A report document carrying exactly the two fields the bridge reads.

    The analyzed scope is taken from the model that was published, so the
    document and the store row genuinely describe one analysis; every test
    that wants them to disagree has to say so explicitly.
    """

    return {
        "source_facts": {
            "analysis_scope": [
                {"path": path}
                for path in sorted(file_id.path for file_id in model.analyzed_files)
            ]
        },
        "integrity": {"digests": {"evaluation": {"value": identity}}},
    }


def _second_model() -> CanonicalModel:
    """A neighbour ANALYSIS over the same paths.

    Same ``analyzed_files`` -- so the same scope receipt -- and one extra
    coupled set, so a different membership and a different run id.  This is
    the corpus shape that separates "addresses the row" from "matches the
    scope"; on a store holding one run per scope the two are indistinguishable.
    """

    model = fixture_model()
    return replace(
        model,
        coupled_sets=frozenset({*model.coupled_sets, frozenset({"OnlyInSecond"})}),
    )


def _publish(store: RunStore, model: CanonicalModel, *, generation: int = 0) -> str:
    return store.write_full_run(
        model, namespace=_NS, target=_TARGET, expected_generation=generation
    ).run_id


def _config(path: Path) -> RunStoreConfig:
    return RunStoreConfig(enabled=True, path=path)


def _linked_store(path: Path, identity: str) -> tuple[str, Mapping[str, object]]:
    """Publish the fixture run, link it to ``identity``, return both halves."""

    model = fixture_model()
    document = _document(model, identity)
    with RunStore(path) as store:
        run_id = _publish(store, model)
        link_run_report(
            store,
            run_id=run_id,
            report_run_identity=identity,
            expected_scope_digest=report_scope_receipt(document),
        )
    return run_id, document


# ---------------------------------------------------------------------------
# Acceptance 1: the stored lane and the recomputed lane are one answer.
# ---------------------------------------------------------------------------


def test_stored_lane_and_recomputed_lane_name_one_run(tmp_path: Path) -> None:
    """Both roads to the relation end at the same store row.

    The lanes are reported, not inferred: a resolution that could not say
    which road it took would make the next property -- "deleting the index
    changes nothing" -- unmeasurable, because a stored answer and a
    recomputed answer would be the same observation.
    """

    store_path = tmp_path / "runs.sqlite"
    run_id, document = _linked_store(store_path, "e" * 64)

    stored = resolve_run_snapshot_link(
        config=_config(store_path), report_document=document
    )
    assert stored.state == RUN_SNAPSHOT_RESOLUTION_RESOLVED
    assert stored.lane == RUN_SNAPSHOT_LANE_STORED
    assert stored.store_run_id == run_id

    with sqlite3.connect(store_path) as raw:
        raw.execute("DELETE FROM run_report_links")

    recomputed = resolve_run_snapshot_link(
        config=_config(store_path), report_document=document
    )
    assert recomputed.lane == RUN_SNAPSHOT_LANE_RECOMPUTED
    assert recomputed.store_run_id == stored.store_run_id
    assert recomputed.report_run_identity == stored.report_run_identity
    assert recomputed.analysis_scope_digest == stored.analysis_scope_digest


# ---------------------------------------------------------------------------
# Acceptance 2: the index is derived, so emptying it loses nothing.
# ---------------------------------------------------------------------------


def test_emptying_the_bridge_table_does_not_lose_the_relation(tmp_path: Path) -> None:
    """The edge is an index over two artifacts, never a third authority.

    Deleting every row must cost a recomputation and nothing else, and the
    index must be re-writable from that recomputation -- otherwise "derived"
    would be a word rather than a property.
    """

    store_path = tmp_path / "runs.sqlite"
    run_id, document = _linked_store(store_path, "e" * 64)
    with sqlite3.connect(store_path) as raw:
        raw.execute("DELETE FROM run_report_links")
        assert raw.execute("SELECT count(*) FROM run_report_links").fetchone()[0] == 0

    recovered = resolve_run_snapshot_link(
        config=_config(store_path), report_document=document
    )
    assert recovered.state == RUN_SNAPSHOT_RESOLUTION_RESOLVED
    assert recovered.store_run_id == run_id

    # Rebuildable, not merely recomputable once: the recovered relation goes
    # back into the index and the stored lane answers again.
    persist_run_snapshot_link(
        store_path=store_path,
        link=bridge_run_snapshot(
            publication=RunSnapshotPublication(
                outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
                admissible=True,
                target=_TARGET,
                run_id=run_id,
                generation=1,
                analysis_scope_digest=recovered.analysis_scope_digest,
            ),
            report_document=document,
        ),
    )
    rebuilt = resolve_run_snapshot_link(
        config=_config(store_path), report_document=document
    )
    assert rebuilt.lane == RUN_SNAPSHOT_LANE_STORED
    assert rebuilt.store_run_id == run_id


# ---------------------------------------------------------------------------
# Acceptance 3: a substituted witness is refused, not matched loosely.
# ---------------------------------------------------------------------------


def test_a_substituted_scope_witness_is_refused(tmp_path: Path) -> None:
    """The edge is found by identity; the witness then has to agree.

    A resolution that fell back to "some run over a similar scope" here
    would hand the caller a valid model of a DIFFERENT tree, and every
    endpoint check would confirm it: the store run verifies against its own
    membership, the document verifies against its own integrity block, and
    only the relation is false.
    """

    store_path = tmp_path / "runs.sqlite"
    _run_id, document = _linked_store(store_path, "e" * 64)
    substituted = dict(document)
    substituted["source_facts"] = {
        "analysis_scope": [{"path": "pkg/not_analyzed_at_all.py"}]
    }

    with pytest.raises(RunSnapshotBridgeError) as refusal:
        resolve_run_snapshot_link(
            config=_config(store_path), report_document=substituted
        )
    assert "scope" in str(refusal.value)


def test_link_refuses_a_write_whose_witness_disagrees(tmp_path: Path) -> None:
    """The same law on the write side: an edge is never stated on faith."""

    store_path = tmp_path / "runs.sqlite"
    model = fixture_model()
    with RunStore(store_path) as store:
        run_id = _publish(store, model)
        with pytest.raises(RunReportLinkError):
            link_run_report(
                store,
                run_id=run_id,
                report_run_identity="e" * 64,
                expected_scope_digest="0" * 64,
            )
        assert linked_run(store, report_run_identity="e" * 64) is None


# ---------------------------------------------------------------------------
# Acceptance 4: the process boundary.
# ---------------------------------------------------------------------------


_RESTART_CHILD = """
import json, pathlib, sys
from codeclone.core.canonical_snapshot import resolve_run_snapshot_link
from codeclone.models import RunStoreConfig

store, document = sys.argv[1], sys.argv[2]
resolution = resolve_run_snapshot_link(
    config=RunStoreConfig(enabled=True, path=pathlib.Path(store)),
    report_document=json.loads(pathlib.Path(document).read_text("utf-8")),
)
print(json.dumps([resolution.state, resolution.lane, resolution.store_run_id]))
"""


def test_the_edge_survives_a_real_process_restart(tmp_path: Path) -> None:
    """A FRESH interpreter, holding only the report document and the file.

    Nothing of the writing process survives into the child: not the store
    handle, not the publication witness, not the in-process link.  This is
    the property the whole change exists for -- the MCP server restarted six
    times on 2026-09-01 and the in-process relation died with each one.
    """

    store_path = tmp_path / "runs.sqlite"
    run_id, document = _linked_store(store_path, "e" * 64)
    document_path = tmp_path / "document.json"
    document_path.write_text(json.dumps(document), "utf-8")

    completed = subprocess.run(
        (sys.executable, "-c", _RESTART_CHILD, str(store_path), str(document_path)),
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(completed.stdout) == [
        RUN_SNAPSHOT_RESOLUTION_RESOLVED,
        RUN_SNAPSHOT_LANE_STORED,
        run_id,
    ]


# ---------------------------------------------------------------------------
# The pin the ruling names separately: the edge addresses a ROW.
# ---------------------------------------------------------------------------


def test_the_edge_addresses_the_row_not_the_scope(tmp_path: Path) -> None:
    """Two analyses over one path set; each document gets its OWN run.

    This is the corpus a scope-keyed relation cannot survive and a
    row-keyed one answers exactly.  Both runs are published, both carry the
    same ``analysis_scope_digest``, and their memberships differ -- the
    everyday shape of "analyze, edit a file, analyze again".
    """

    store_path = tmp_path / "runs.sqlite"
    first_model, second_model = fixture_model(), _second_model()
    first_document = _document(first_model, "a" * 64)
    second_document = _document(second_model, "b" * 64)
    scope = report_scope_receipt(first_document)
    assert report_scope_receipt(second_document) == scope  # one scope, two runs

    with RunStore(store_path) as store:
        first_run = _publish(store, first_model)
        second_run = _publish(store, second_model, generation=1)
        assert first_run != second_run
        assert sorted(runs_over_scope(store, scope_digest=scope)) == sorted(
            (first_run, second_run)
        )
        for run_id, identity in ((first_run, "a" * 64), (second_run, "b" * 64)):
            link_run_report(
                store,
                run_id=run_id,
                report_run_identity=identity,
                expected_scope_digest=scope,
            )

    config = _config(store_path)
    assert (
        resolve_run_snapshot_link(
            config=config, report_document=first_document
        ).store_run_id
        == first_run
    )
    assert (
        resolve_run_snapshot_link(
            config=config, report_document=second_document
        ).store_run_id
        == second_run
    )


def test_one_store_record_answers_many_report_identities(tmp_path: Path) -> None:
    """The measured one-to-many, persisted.

    One analysis evaluated under two gate requests is one store row and two
    report identities.  The persisted edge must hold BOTH pairs: a relation
    that could keep only one would silently forget whichever document was
    linked first, and the forgetting would look exactly like "that run was
    never stored".
    """

    store_path = tmp_path / "runs.sqlite"
    model = fixture_model()
    documents = [_document(model, character * 64) for character in ("a", "b")]
    with RunStore(store_path) as store:
        run_id = _publish(store, model)
        for character, document in zip(("a", "b"), documents, strict=True):
            link_run_report(
                store,
                run_id=run_id,
                report_run_identity=character * 64,
                expected_scope_digest=report_scope_receipt(document),
            )
        edges = [
            linked_run(store, report_run_identity=character * 64)
            for character in ("a", "b")
        ]
    assert [edge.run_id for edge in edges if edge is not None] == [run_id, run_id]
    assert [edge.report_run_identity for edge in edges if edge is not None] == [
        "a" * 64,
        "b" * 64,
    ]


def test_relinking_the_same_pair_is_idempotent(tmp_path: Path) -> None:
    """A re-run over an unchanged tree states the same edge, not a second one."""

    store_path = tmp_path / "runs.sqlite"
    run_id, document = _linked_store(store_path, "e" * 64)
    with RunStore(store_path) as store:
        link_run_report(
            store,
            run_id=run_id,
            report_run_identity="e" * 64,
            expected_scope_digest=report_scope_receipt(document),
        )
    with sqlite3.connect(store_path) as raw:
        assert raw.execute("SELECT count(*) FROM run_report_links").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Every refusal has an input that reaches it.
# ---------------------------------------------------------------------------


def test_recompute_refuses_an_ambiguous_scope(tmp_path: Path) -> None:
    """With no edge and two runs over one scope, the answer is a refusal.

    Guessing here is the whole defect class: both candidates verify against
    their own membership, so a picked one would be indistinguishable from
    the right one at every endpoint.
    """

    store_path = tmp_path / "runs.sqlite"
    with RunStore(store_path) as store:
        _publish(store, fixture_model())
        _publish(store, _second_model(), generation=1)
    with pytest.raises(RunSnapshotBridgeError) as refusal:
        resolve_run_snapshot_link(
            config=_config(store_path),
            report_document=_document(fixture_model(), "e" * 64),
        )
    assert "ambiguous" in str(refusal.value)


def test_resolve_refuses_two_edges_for_one_report_identity(tmp_path: Path) -> None:
    """One evaluation cannot descend from two analyses.

    Only a defect or a hand-written row can produce this shape, which is
    exactly why the read refuses it instead of taking the first: an index
    whose corruption resolves to "some run" is worse than no index.
    """

    store_path = tmp_path / "runs.sqlite"
    _run_id, document = _linked_store(store_path, "e" * 64)
    with RunStore(store_path) as store:
        second = _publish(store, _second_model(), generation=1)
        link_run_report(
            store,
            run_id=second,
            report_run_identity="f" * 64,
            expected_scope_digest=report_scope_receipt(document),
        )
    with sqlite3.connect(store_path) as raw:
        raw.execute(
            "UPDATE run_report_links SET report_run_identity = ? "
            "WHERE report_run_identity = ?",
            ("e" * 64, "f" * 64),
        )
    with pytest.raises(RunReportLinkError) as refusal:
        resolve_run_snapshot_link(config=_config(store_path), report_document=document)
    assert "linked to 2 analysis runs" in str(refusal.value)


def test_resolve_says_unlinked_when_no_run_answers(tmp_path: Path) -> None:
    """An empty store is a state, not a refusal: nothing backs this document."""

    store_path = tmp_path / "runs.sqlite"
    with RunStore(store_path):
        pass
    resolution = resolve_run_snapshot_link(
        config=_config(store_path),
        report_document=_document(fixture_model(), "e" * 64),
    )
    assert resolution.state == RUN_SNAPSHOT_RESOLUTION_UNLINKED
    assert resolution.store_run_id == ""


def test_resolve_refuses_a_store_that_is_not_there(tmp_path: Path) -> None:
    """An absent store is not the statement that no run backs a document."""

    with pytest.raises(RunSnapshotBridgeError):
        resolve_run_snapshot_link(
            config=_config(tmp_path / "absent.sqlite"),
            report_document=_document(fixture_model(), "e" * 64),
        )


def test_resolve_refuses_a_disabled_rollout(tmp_path: Path) -> None:
    """A disabled backend cannot answer, and must not pretend to."""

    with pytest.raises(RunSnapshotBridgeError):
        resolve_run_snapshot_link(
            config=RunStoreConfig(),
            report_document=_document(fixture_model(), "e" * 64),
        )


def test_link_refuses_an_edge_that_names_no_report(tmp_path: Path) -> None:
    """An edge keyed by the empty identity is an orphan by construction.

    ``report_run_identity`` never returns an empty string, so nothing would
    ever look this row up again: it would sit in the index forever, invisible
    to every reader and counted by every sweep.  The input reaches the guard
    from any direct caller of this public store operation.
    """

    store_path = tmp_path / "runs.sqlite"
    model = fixture_model()
    document = _document(model, "e" * 64)
    with RunStore(store_path) as store:
        run_id = _publish(store, model)
        with pytest.raises(RunReportLinkError):
            link_run_report(
                store,
                run_id=run_id,
                report_run_identity="",
                expected_scope_digest=report_scope_receipt(document),
            )
    with sqlite3.connect(store_path) as raw:
        assert raw.execute("SELECT count(*) FROM run_report_links").fetchone()[0] == 0


def test_link_refuses_a_run_the_store_does_not_hold(tmp_path: Path) -> None:
    """An edge to a row that is not there is not an edge."""

    store_path = tmp_path / "runs.sqlite"
    model = fixture_model()
    document = _document(model, "e" * 64)
    with RunStore(store_path) as store:
        _publish(store, model)
        with pytest.raises(UnknownRunError):
            link_run_report(
                store,
                run_id="0" * 64,
                report_run_identity="e" * 64,
                expected_scope_digest=report_scope_receipt(document),
            )


# ---------------------------------------------------------------------------
# Writing the edge presupposes the store; it never brings one about.
# ---------------------------------------------------------------------------
#
# The edge is stated about an ALREADY published run, so a store at the named
# path is this write's precondition and never its result.  Three inputs, three
# answers, and the two refusals are told apart by their ``reason`` token:
#
#   store absent                          -> run_store_absent
#   store present, run never published    -> run_not_published
#   store present, run published          -> the edge is written
#
# Collapsing the first two rows is the measured defect this table exists for:
# the creating default built the store, then reported ``run_not_published`` --
# a true sentence about the store it had just written, and a false one about
# the store the caller named.


def _link_to_an_unheld_run(document: Mapping[str, object]) -> RunSnapshotLink:
    """A ``linked`` bridge naming a run no store in these tests ever held.

    ``linked`` is the only state that carries both halves of the relation, so
    it is the only state that reaches the store at all; the two zero states
    return ``False`` without opening anything and would measure nothing here.
    """

    return bridge_run_snapshot(
        publication=RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
            admissible=True,
            target=_TARGET,
            run_id="a" * 64,
            generation=1,
            analysis_scope_digest=report_scope_receipt(document),
        ),
        report_document=document,
    )


def test_persisting_into_an_absent_store_creates_no_store(tmp_path: Path) -> None:
    """Row 1: no store here, and none after the refusal either.

    Measured before this pin: the absent path was opened with the creating
    default, which left 69632 bytes and eleven tables of empty schema behind
    and then refused with ``run_not_published``.  The parent directory is
    pinned with the file because the shared connection owner creates it
    before it ever reaches sqlite, so a guard placed one statement later
    would still leave a tree on disk.
    """

    store_path = tmp_path / "not-a-store" / "runs.sqlite"
    document = _document(fixture_model(), "e" * 64)

    with pytest.raises(UnknownRunError) as refusal:
        persist_run_snapshot_link(
            store_path=store_path, link=_link_to_an_unheld_run(document)
        )

    assert refusal.value.reason == "run_store_absent"
    assert not store_path.exists(), "the refused write became the store it refused"
    assert not store_path.parent.exists(), "the refused write created the store's dir"


def test_persisting_a_run_the_store_never_published_says_exactly_that(
    tmp_path: Path,
) -> None:
    """Row 2: the store is real, the run is not.

    The distinction between this row and the one above exists only if BOTH
    tokens can be observed: one reason for "nothing to link to" would leave
    an absent store and an unpublished run indistinguishable to every caller
    that branches on ``reason``, which is what the token is for.
    """

    store_path = tmp_path / "runs.sqlite"
    with RunStore(store_path):
        pass
    document = _document(fixture_model(), "e" * 64)

    with pytest.raises(UnknownRunError) as refusal:
        persist_run_snapshot_link(
            store_path=store_path, link=_link_to_an_unheld_run(document)
        )

    assert refusal.value.reason == "run_not_published"
    assert store_path.exists(), "the refusal removed the store it was handed"


def test_persisting_a_published_run_writes_the_edge(tmp_path: Path) -> None:
    """Row 3: the precondition holds, so the write happens.

    The positive row belongs to the same table as the two refusals.  Without
    it a guard that refused every input would satisfy both rows above and
    leave the owner unable to do the one thing it is for.
    """

    store_path = tmp_path / "runs.sqlite"
    model = fixture_model()
    document = _document(model, "e" * 64)
    with RunStore(store_path) as store:
        run_id = _publish(store, model)

    persisted = persist_run_snapshot_link(
        store_path=store_path,
        link=bridge_run_snapshot(
            publication=RunSnapshotPublication(
                outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
                admissible=True,
                target=_TARGET,
                run_id=run_id,
                generation=1,
                analysis_scope_digest=report_scope_receipt(document),
            ),
            report_document=document,
        ),
    )

    assert persisted is True
    with RunStore(store_path) as store:
        edge = linked_run(store, report_run_identity="e" * 64)
    assert edge is not None
    assert edge.run_id == run_id


# ---------------------------------------------------------------------------
# The index never outlives what it addresses.
# ---------------------------------------------------------------------------


def test_gc_drops_the_edge_with_the_run_it_addressed(tmp_path: Path) -> None:
    """A collected run takes its edges with it.

    Two properties in one measurement: the sweep is not refused by the
    foreign key (an index that could deadlock the collector would be a
    liability), and the index does not survive as a pointer into a deleted
    row.  The edge also does not ROOT the run: a derived index may not
    extend retention, or it would quietly become an authority.
    """

    store_path = tmp_path / "runs.sqlite"
    model = fixture_model()
    document = _document(model, "e" * 64)
    with RunStore(store_path) as store:
        first = _publish(store, model)
        link_run_report(
            store,
            run_id=first,
            report_run_identity="e" * 64,
            expected_scope_digest=report_scope_receipt(document),
        )
        _publish(store, _second_model(), generation=1)  # advance the head off `first`
        report = collect_garbage(store, retain_history=0)
        assert linked_run(store, report_run_identity="e" * 64) is None
    # The run really was swept -- an index emptied because nothing was
    # collected would prove nothing at all.
    assert dict(report.collected)[GC_COLLECT_UNREACHABLE] == 1
    with sqlite3.connect(store_path) as raw:
        assert raw.execute("SELECT count(*) FROM run_report_links").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# The producer edge writes it, or the whole change is a function nobody calls.
# ---------------------------------------------------------------------------


def test_the_producer_edge_persists_the_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Driving the real pipeline leaves the edge on disk.

    Without this, dropping the persist call from ``core/reporting.py``
    leaves every test above green: they all write the edge themselves.
    """

    from tests.test_run_store_identity_bridge import _report_case

    store_path = tmp_path / "runs.sqlite"
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store_path))
    artifacts = _report_case(
        tmp_path / "tree", json_out=tmp_path / "out.json", store=store_path
    )
    link = artifacts.run_snapshot_link
    assert link is not None
    with RunStore(store_path) as store:
        edge = linked_run(store, report_run_identity=link.report_run_identity)
    assert edge is not None
    assert edge.run_id == link.store_run_id
    assert edge.analysis_scope_digest == link.analysis_scope_digest
