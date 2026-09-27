# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The bridge edge the store could not take: ``unrecorded``, and only that.

Ruling 2026-09-25 (protocol C, last): the publication is stored and the
report is sealed; only the edge between them -- the second write -- met a
store that could not take it right now.  That one outcome, and only for the
store's own ``StoreUnavailableError`` (a held lock after the bounded wait, a
read-only medium, an I/O fault), is a state of the relation rather than a
failure of the analysis: the link says ``unrecorded`` and carries the
refusal, every report is written, the exit code does not move, the CLI
prints one warning and MCP adds it to ``warnings[]``.  Every other failure
at that step stays loud.  The orphan run is ordinary retention: nothing
repairs it, the next analysis publishes a fresh run with its own edge.

Measured on 28112eef before this module: a write lock another connection
held at the edge write took the CLI down with ``INTERNAL ERROR`` (exit 5,
no report written) and the MCP call with the raw refusal.

Every store lives under ``tmp_path``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import codeclone.core.reporting as reporting_module
import codeclone.utils.sqlite_store as sqlite_store
from codeclone.api.run_store_serving import (
    SERVING_REASON_SERVED,
    SERVING_SOURCE_RUN_STORE,
    read_run_store_slices,
)
from codeclone.canonical import store as store_module
from codeclone.canonical.errors import (
    UNKNOWN_RUN_NOT_PUBLISHED,
    RunReportLinkError,
    StoreIntegrityError,
    UnknownRunError,
)
from codeclone.canonical.store import RunStore, collect_garbage
from codeclone.models import (
    RUN_SNAPSHOT_LINK_LINKED,
    RUN_SNAPSHOT_LINK_STATES,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RunSnapshotLink,
)
from tests.conftest import RunStoreCorpusRunner, RunStoreMcpRunner

_UNRECORDED = "unrecorded"
_WARNING_HEAD = "report-to-snapshot link was not recorded: "
_WARNING_TAIL = (
    "; analysis and reports are complete; the next analysis publishes a fresh run"
)
_ARGS = ("--fail-health", "0", "--min-loc", "3", "--min-stmt", "2")
_DIGEST = "d" * 64


def _write_tree(root: Path, tag: str = "a") -> None:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    units = "\n\n".join(
        f"def unit_{tag}_{index}(value: int) -> int:\n"
        f'    """Unit {index}."""\n'
        f"    return value + {index}\n"
        for index in range(12)
    )
    (package / "gen.py").write_text(f'"""Gen {tag}."""\n\n\n{units}', "utf-8")


def _corpus(tmp_path: Path) -> tuple[Path, Path]:
    """A corpus to analyse and the store path its publications go to."""
    root = (tmp_path / "corpus").resolve()
    _write_tree(root)
    return root, tmp_path / "runs.sqlite3"


@pytest.fixture
def links(monkeypatch: pytest.MonkeyPatch) -> list[RunSnapshotLink]:
    """Every bridge witness the process mints, read on its class."""
    minted: list[RunSnapshotLink] = []
    real = RunSnapshotLink.__post_init__

    def recorded(link: RunSnapshotLink) -> None:
        real(link)
        minted.append(link)

    monkeypatch.setattr(RunSnapshotLink, "__post_init__", recorded)
    return minted


@dataclass
class _EdgeLock:
    """While ``armed``, another connection holds the write lock exactly while
    the bridge edge is written and lets go the moment the write returns."""

    armed: bool = True
    met: int = 0


@pytest.fixture
def edge_lock(monkeypatch: pytest.MonkeyPatch) -> _EdgeLock:
    """The busy timeout is shortened so the bounded wait ends in a fraction
    of a second; ``met`` counts the edge writes that met the lock."""
    monkeypatch.setattr(sqlite_store, "_SQLITE_BUSY_TIMEOUT_MS", 200)
    real = store_module.link_run_report
    lock = _EdgeLock()

    def maybe_locked(store: RunStore, **kwargs: str) -> object:
        if not lock.armed:
            return real(store, **kwargs)
        holder = sqlite3.connect(store._path, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        lock.met += 1
        try:
            return real(store, **kwargs)
        finally:
            holder.execute("ROLLBACK")
            holder.close()

    monkeypatch.setattr(store_module, "link_run_report", maybe_locked)
    return lock


def _store_rows(db: Path) -> tuple[list[str], int, int]:
    with RunStore(db, create=False) as store:
        connection = store._connection
        runs = [str(row[0]) for row in connection.execute("SELECT run_id FROM runs")]
        edges = int(
            connection.execute("SELECT COUNT(*) FROM run_report_links").fetchone()[0]
        )
        leases = int(
            connection.execute("SELECT COUNT(*) FROM run_leases").fetchone()[0]
        )
    return runs, edges, leases


# -- the state and its carrier -----------------------------------------------


def _unrecorded(**overrides: object) -> RunSnapshotLink:
    fields: dict[str, object] = {
        "state": _UNRECORDED,
        "outcome": RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        "store_run_id": "s" * 64,
        "analysis_scope_digest": _DIGEST,
        "report_run_identity": "r" * 64,
        "refusal": "StoreUnavailableError: run store at x is unavailable",
    }
    fields.update(overrides)
    return RunSnapshotLink(**fields)  # type: ignore[arg-type]


def test_unrecorded_is_a_state_that_carries_both_halves_and_the_refusal() -> None:
    link = _unrecorded()
    assert _UNRECORDED in RUN_SNAPSHOT_LINK_STATES
    assert link.refusal.startswith("StoreUnavailableError: ")
    with pytest.raises(ValueError, match="carries the store's refusal"):
        _unrecorded(refusal="")
    with pytest.raises(ValueError, match="carries the store's refusal"):
        replace(link, state=RUN_SNAPSHOT_LINK_LINKED)
    with pytest.raises(ValueError, match="both addresses"):
        _unrecorded(store_run_id="")
    with pytest.raises(ValueError, match="both addresses"):
        _unrecorded(report_run_identity="")


def test_only_an_unrecorded_link_has_a_warning_and_it_names_the_refusal() -> None:
    link = _unrecorded()
    assert link.warnings() == (_WARNING_HEAD + link.refusal + _WARNING_TAIL,)
    linked = replace(link, state=RUN_SNAPSHOT_LINK_LINKED, refusal="")
    assert linked.warnings() == ()


def test_an_unrecorded_link_is_still_served_at_its_store_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The edge is an index; the publisher still holds the run's address,
    and the serving door reads the store at it exactly as for ``linked``."""
    from tests.test_canonical_roundtrip import fixture_model

    db = tmp_path / ".codeclone" / "db" / "runs.sqlite3"
    db.parent.mkdir(parents=True)
    with RunStore(db) as store:
        run_id = store.write_full_run(
            fixture_model(), namespace="n", target="t", expected_generation=0
        ).run_id
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(db))
    slices, outcome = read_run_store_slices(
        root=tmp_path, link=_unrecorded(store_run_id=run_id)
    )
    assert slices is not None
    assert (outcome.source, outcome.reason) == (
        SERVING_SOURCE_RUN_STORE,
        SERVING_REASON_SERVED,
    )


# -- the CLI: the edge write meets a held lock --------------------------------


def test_a_locked_edge_write_leaves_the_link_unrecorded_and_the_run_complete(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    edge_lock: _EdgeLock,
    links: list[RunSnapshotLink],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The run is stored, the report is written, the lease is released, one
    warning line names the refusal, and the exit code is the one the same
    analysis answers with the edge unlocked."""
    root, locked_db = _corpus(tmp_path)
    report = root / "report.json"
    code = run_store_cli(root, *_ARGS, "--json", str(report), store=locked_db)
    printed = " ".join(capsys.readouterr().out.split())
    assert report.exists(), "the JSON report was not written"
    assert json.loads(report.read_text("utf-8"))["meta"]
    assert edge_lock.met == 1
    link = links[-1]
    assert link.state == _UNRECORDED
    assert link.refusal.startswith("StoreUnavailableError: ")
    assert "database is locked" in link.refusal
    assert _WARNING_HEAD.strip() in printed
    runs, edges, leases = _store_rows(locked_db)
    assert (runs, edges, leases) == ([link.store_run_id], 0, 0), (
        "the run is stored, the edge is not, the in-flight lease is released"
    )

    edge_lock.armed = False
    report.unlink()
    control_db = tmp_path / "control.sqlite3"
    control = run_store_cli(root, *_ARGS, "--json", str(report), store=control_db)
    assert links[-1].state == RUN_SNAPSHOT_LINK_LINKED
    assert control == code
    assert _store_rows(control_db)[1] == 1


def test_the_orphan_run_is_left_to_retention_and_the_next_analysis_links_its_own(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    edge_lock: _EdgeLock,
    links: list[RunSnapshotLink],
) -> None:
    """Nothing repairs the orphan: the next analysis of a changed tree
    publishes a fresh run and records that run's edge; the orphan keeps no
    edge and is one more candidate of the next sweep."""
    root, db = _corpus(tmp_path)
    run_store_cli(root, *_ARGS, "--json", str(root / "a.json"), store=db)
    orphan = links[-1]
    assert orphan.state == _UNRECORDED
    edge_lock.armed = False
    _write_tree(root, "b")
    run_store_cli(root, *_ARGS, "--json", str(root / "b.json"), store=db)
    fresh = links[-1]
    assert fresh.state == RUN_SNAPSHOT_LINK_LINKED
    assert fresh.store_run_id != orphan.store_run_id
    with RunStore(db, create=False) as store:
        edges = dict(
            store._connection.execute(
                "SELECT r.run_id, COUNT(l.run_pk) FROM runs r "
                "LEFT JOIN run_report_links l ON l.run_pk = r.run_pk "
                "GROUP BY r.run_id"
            ).fetchall()
        )
        swept = collect_garbage(store, retain_history=2)
    assert edges == {orphan.store_run_id: 0, fresh.store_run_id: 1}
    assert swept.candidates == 2


# -- every other failure at the edge stays loud --------------------------------


def _unknown_run(**_kwargs: object) -> bool:
    raise UnknownRunError("the leased run is gone", reason=UNKNOWN_RUN_NOT_PUBLISHED)


def _integrity(**_kwargs: object) -> bool:
    raise StoreIntegrityError("the edge table cannot be read")


def _relation(**_kwargs: object) -> bool:
    raise RunReportLinkError("the two halves disagree")


def _defect(**_kwargs: object) -> bool:
    raise ValueError("a programming error at the edge")


@pytest.mark.parametrize(
    "failure",
    [_unknown_run, _integrity, _relation, _defect],
    ids=["unknown-run", "integrity", "relation", "defect"],
)
def test_any_other_failure_at_the_edge_write_stays_loud(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    monkeypatch: pytest.MonkeyPatch,
    failure: object,
) -> None:
    root, db = _corpus(tmp_path)
    monkeypatch.setattr(reporting_module, "persist_run_snapshot_link", failure)
    with pytest.raises(AssertionError, match="INTERNAL_ERROR: 5"):
        run_store_cli(root, *_ARGS, "--json", str(root / "report.json"), store=db)
    assert _store_rows(db)[2] == 0, "the lease outlived a loud failure"


# -- MCP: the same line, in the answer's own warnings --------------------------


def test_mcp_answers_with_the_unrecorded_warning_and_keeps_the_run(
    tmp_path: Path,
    run_store_mcp: RunStoreMcpRunner,
    edge_lock: _EdgeLock,
    links: list[RunSnapshotLink],
) -> None:
    root, db = _corpus(tmp_path)
    answer = run_store_mcp(root, db)
    assert edge_lock.met == 1
    link = links[-1]
    assert link.state == _UNRECORDED
    warnings = [str(item) for item in answer["warnings"]]  # type: ignore[attr-defined]
    assert _WARNING_HEAD + link.refusal + _WARNING_TAIL in warnings
    assert answer["run_id"]
    assert _store_rows(db)[1:] == (0, 0)
