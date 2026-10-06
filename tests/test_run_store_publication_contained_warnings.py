# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The two contained store steps after a publication are said, not dropped.

After the publishing transaction commits, two more store steps run: the GC
owner's sweep, and -- once the bridge is stated -- the release of the
publisher's in-flight lease.  Both are contained on purpose (the run is
stored, the reports are complete), and both were silent: measured on the tip
before this change with a second connection holding ``BEGIN IMMEDIATE``, the
sweep's refusal receipt (``RunSnapshotPublication.collection``) had no
reader anywhere, and ``report`` dropped the release's ``False`` -- the
``active`` lease stayed for its day, and the CLI printed nothing.

Each now rides the run-snapshot link, the carrier whose ``warnings()`` the
CLI prints as runtime warnings and MCP returns in ``warnings[]`` -- the same
channel that says "publication failed".  The exit code does not move, and a
step the store did not refuse says nothing.

The lock is held by a second connection over a store under ``tmp_path``;
the handles that meet it are made to give up at once instead of waiting out
the shared five-second busy timeout, so the refusal is SQLite's own
``database is locked`` reached through the real ``BEGIN IMMEDIATE``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import pytest

import codeclone.core.canonical_snapshot as snapshot_module
from codeclone.canonical import store as store_module
from codeclone.canonical.store import RunStore
from codeclone.core.canonical_snapshot import (
    bridge_run_snapshot,
    release_publication_lease,
)
from codeclone.models import (
    CANONICAL_HEAD_TARGET,
    RUN_SNAPSHOT_LINK_UNEVALUATED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    GcJobReport,
    RunSnapshotLink,
    RunSnapshotPublication,
    RunStoreConfig,
)
from tests.conftest import RunStoreCorpusRunner, RunStoreMcpRunner
from tests.test_canonical_roundtrip import fixture_model

_ARGS: Final = ("--fail-health", "0", "--min-loc", "3", "--min-stmt", "2")
_SWEEP: Final = "run store was not swept after this publication"
_LEASE: Final = "run store publication lease was not released"
_LOCKED: Final = "database is locked"


_UNITS: Final = "".join(
    f'\n\ndef unit_{index}(value: int) -> int:\n    """Unit {index}."""\n'
    f"    return value * {index}\n"
    for index in range(10)
)


def _corpus(tmp_path: Path) -> Path:
    """A one-package tree the analysis publishes in well under a second."""
    package = (tmp_path / "corpus" / "pkg").resolve()
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "units.py").write_text(f'"""Units."""\n{_UNITS}', "utf-8")
    return package.parent


@dataclass
class _HeldLock:
    """A second connection holding the store's write lock from the moment
    the publication's sweep begins until the test lets it go."""

    path: Path
    blocker: sqlite3.Connection | None = None
    met: list[str] = field(default_factory=list)

    def engage(self) -> None:
        if self.blocker is None:
            self.blocker = sqlite3.connect(self.path, isolation_level=None)
            self.blocker.execute("BEGIN IMMEDIATE")

    def release(self) -> None:
        if self.blocker is not None:
            self.blocker.execute("ROLLBACK")
            self.blocker.close()
            self.blocker = None


@pytest.fixture
def held_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_HeldLock]:
    """Hold the lock over every post-publication step; the handles that meet
    it give up at once instead of waiting five seconds each."""
    lock = _HeldLock(tmp_path / "runs.sqlite3")
    collect = snapshot_module._collect_after_publication
    release = store_module.release_run_lease
    link = store_module.link_run_report

    def collect_under_the_lock(store: RunStore) -> GcJobReport:
        lock.engage()
        store._connection.execute("PRAGMA busy_timeout = 0")
        lock.met.append("sweep")
        return collect(store)

    def release_under_the_lock(store: RunStore, lease_id: str) -> bool:
        store._connection.execute("PRAGMA busy_timeout = 0")
        lock.met.append("release")
        return release(store, lease_id)

    def link_under_the_lock(store: RunStore, **kwargs: object) -> object:
        store._connection.execute("PRAGMA busy_timeout = 0")
        return link(store, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        snapshot_module, "_collect_after_publication", collect_under_the_lock
    )
    monkeypatch.setattr(store_module, "release_run_lease", release_under_the_lock)
    monkeypatch.setattr(store_module, "link_run_report", link_under_the_lock)
    try:
        yield lock
    finally:
        lock.release()


def _printed(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(capsys.readouterr().out.split())


def _lease_kinds(path: Path) -> list[str]:
    with RunStore(path, create=False) as store:
        rows = store._connection.execute("SELECT kind FROM run_leases").fetchall()
    return [str(row[0]) for row in rows]


# -- the carriers --------------------------------------------------------------


def _stored(collection: GcJobReport) -> RunSnapshotPublication:
    return RunSnapshotPublication(
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        admissible=True,
        target=CANONICAL_HEAD_TARGET,
        run_id="r" * 64,
        generation=1,
        analysis_scope_digest="s" * 64,
        collection=collection,
        in_flight_lease="publication:1:lease",
    )


def test_the_bridge_reads_the_sweep_receipt_and_the_link_says_one_line() -> None:
    refused = bridge_run_snapshot(
        publication=_stored(
            GcJobReport.refused(
                job="canonical_run_store",
                refusal="sweep not completed: OperationalError: database is locked",
            )
        ),
        report_document=None,
    )
    assert refused.state == RUN_SNAPSHOT_LINK_UNEVALUATED
    assert refused.warnings() == (
        "run store was not swept after this publication: sweep not completed: "
        "OperationalError: database is locked; analysis and reports are "
        "complete; the next publication sweeps again",
    )
    swept = bridge_run_snapshot(
        publication=_stored(GcJobReport(job="canonical_run_store", candidates=0)),
        report_document=None,
    )
    assert (swept.sweep_refusal, swept.warnings()) == ("", ())


def test_a_refused_release_is_a_line_and_only_a_stored_link_carries_one() -> None:
    link = RunSnapshotLink(
        state=RUN_SNAPSHOT_LINK_UNEVALUATED,
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        store_run_id="r" * 64,
        analysis_scope_digest="s" * 64,
        lease_refusal="OperationalError: database is locked",
    )
    assert link.warnings() == (
        "run store publication lease was not released: OperationalError: "
        "database is locked; analysis and reports are complete; an unreleased "
        "lease holds its run until the lease's deadline",
    )
    for carried in ("sweep_refusal", "lease_refusal"):
        with pytest.raises(ValueError, match="stored publication only"):
            RunSnapshotLink(
                state=RUN_SNAPSHOT_LINK_UNEVALUATED,
                outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
                **{carried: "refused"},
            )


# -- the release names what the store refused ------------------------------------


def _leased_store(path: Path) -> RunSnapshotPublication:
    with RunStore(path) as store:
        receipt = store.write_full_run(
            fixture_model(),
            namespace="codeclone.analysis",
            target=CANONICAL_HEAD_TARGET,
            expected_generation=0,
            in_flight_lease=("publication:1:lease", 3600),
        )
    return RunSnapshotPublication(
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        admissible=True,
        target=CANONICAL_HEAD_TARGET,
        run_id=receipt.run_id,
        generation=receipt.generation,
        analysis_scope_digest=receipt.analysis_scope_digest,
        collection=GcJobReport(job="canonical_run_store", candidates=0),
        in_flight_lease="publication:1:lease",
    )


def test_the_release_returns_the_stores_refusal_and_nothing_on_success(
    held_lock: _HeldLock,
) -> None:
    publication = _leased_store(held_lock.path)
    config = RunStoreConfig(enabled=True, path=held_lock.path)
    held_lock.engage()
    refusal = release_publication_lease(config=config, publication=publication)
    assert held_lock.met == ["release"]
    assert _LOCKED in refusal and refusal.startswith("OperationalError: ")
    held_lock.release()
    assert _lease_kinds(held_lock.path) == ["active"]
    assert release_publication_lease(config=config, publication=publication) == ""
    assert _lease_kinds(held_lock.path) == []


# -- the CLI: one runtime line each, the same exit --------------------------------


def test_the_cli_says_a_refused_sweep_and_a_refused_release_once_each(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    held_lock: _HeldLock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _corpus(tmp_path)
    code = run_store_cli(root, *_ARGS, store=held_lock.path)
    printed = _printed(capsys)
    assert held_lock.met == ["sweep", "release"], "the lock met no step"
    assert printed.count(_SWEEP) == 1, printed
    assert printed.count(_LEASE) == 1, printed
    assert printed.count(_LOCKED) == 2, printed
    held_lock.release()
    assert _lease_kinds(held_lock.path) == ["active"]

    control = run_store_cli(root, *_ARGS, store=tmp_path / "control.sqlite3")
    quiet = _printed(capsys)
    assert _SWEEP not in quiet and _LEASE not in quiet, quiet
    assert control == code


def test_mcp_answers_the_same_two_lines_in_its_warnings(
    tmp_path: Path, run_store_mcp: RunStoreMcpRunner, held_lock: _HeldLock
) -> None:
    root = _corpus(tmp_path)
    answer = run_store_mcp(root, held_lock.path)
    warnings = [str(item) for item in answer["warnings"]]  # type: ignore[attr-defined]
    assert held_lock.met == ["sweep", "release"], "the lock met no step"
    assert sum(item.startswith(_SWEEP) for item in warnings) == 1, warnings
    assert sum(item.startswith(_LEASE) for item in warnings) == 1, warnings
    held_lock.release()

    quiet = run_store_mcp(root, tmp_path / "control.sqlite3")
    quiet_warnings = [str(item) for item in quiet["warnings"]]  # type: ignore[attr-defined]
    assert not any(item.startswith((_SWEEP, _LEASE)) for item in quiet_warnings), (
        quiet_warnings
    )
