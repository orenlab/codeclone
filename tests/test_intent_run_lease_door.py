# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The intent run-lease door: a held grant, or the store's refusal by name.

Every reason the door can answer is reached here against a real store file
in a temporary directory, and the store's own clock is driven so a renewal
is seen to move the deadline.  A store another connection holds the write
lock on answers ``store_unavailable`` on a grant and on a release, never the
raw ``sqlite3`` error the store's lease writes leave unclassified.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from codeclone.api.intent_run_lease import (
    RUN_LEASE_HELD,
    RUN_LEASE_KIND,
    RUN_LEASE_REASONS,
    RUN_LEASE_REFUSED,
    RUN_LEASE_RELEASED,
    RunLeaseState,
    acquire_intent_run_lease,
    release_intent_run_lease,
    renew_intent_run_lease,
    run_lease_id,
)
from codeclone.api.run_store_serving import (
    SERVING_REASON_INCOMPATIBLE_GENERATION,
    SERVING_REASON_INTEGRITY,
    SERVING_REASON_NOT_PUBLISHED,
    SERVING_REASON_RUN_NOT_PUBLISHED,
    SERVING_REASON_STORE_ABSENT,
    SERVING_REASON_STORE_DISABLED,
    SERVING_REASON_STORE_UNAVAILABLE,
)
from codeclone.canonical import RunStore
from codeclone.canonical.store import acquire_run_lease
from codeclone.models import (
    RUN_SNAPSHOT_LINK_LINKED,
    RUN_SNAPSHOT_LINK_UNPUBLISHED,
    RUN_SNAPSHOT_PUBLICATION_DISABLED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RunSnapshotLink,
)
from tests.test_canonical_roundtrip import fixture_model

_GENERATION_1 = Path(__file__).parent / "fixtures" / "run_store_generation_1"
_LEASE_CLOCK = "codeclone.canonical.store._lease_now"
# The shared connection owner's busy timeout, shortened so a held lock
# answers in milliseconds instead of five seconds.
_BUSY_TIMEOUT = "codeclone.utils.sqlite_store._SQLITE_BUSY_TIMEOUT_MS"


@pytest.fixture
def published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    # Inside the root's own ``.codeclone/``: every test below takes its lease
    # with ``root=tmp_path``, and a lease is written only inside the root's
    # service directories (the boundary cases are pinned further down).
    path = tmp_path / ".codeclone" / "db" / "runs.sqlite3"
    path.parent.mkdir(parents=True)
    with RunStore(path) as store:
        run_id = store.write_full_run(
            fixture_model(),
            namespace="lease-door",
            target="worktree",
            expected_generation=0,
        ).run_id
    _enable(monkeypatch, path)
    return path, run_id


def _enable(monkeypatch: pytest.MonkeyPatch, store: Path) -> None:
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store))


def _linked(run_id: str) -> RunSnapshotLink:
    return RunSnapshotLink(
        state=RUN_SNAPSHOT_LINK_LINKED,
        outcome=RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        store_run_id=run_id,
        analysis_scope_digest="0" * 64,
        report_run_identity="1" * 64,
    )


def _lease_rows(path: Path) -> list[tuple[str, str, int]]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [
            (str(lease_id), str(kind), int(expires))
            for lease_id, kind, expires in connection.execute(
                "SELECT lease_id, kind, expires_at FROM run_leases ORDER BY lease_id"
            )
        ]
    finally:
        connection.close()


def _acquire(
    root: Path, run_id: str, lease_id: str = "intent:1:2:3:i"
) -> RunLeaseState:
    return acquire_intent_run_lease(
        root=root, link=_linked(run_id), lease_id=lease_id, ttl_seconds=600
    )


# ── held, renewed, released ───────────────────────────────────────────────


def test_a_published_run_is_held_by_a_session_lease(
    published: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, run_id = published
    monkeypatch.setattr(_LEASE_CLOCK, lambda: 1_000)

    state = _acquire(tmp_path, run_id)

    assert state.held
    assert state.reason == RUN_LEASE_HELD
    assert state.store_run_id == run_id
    assert state.expires_at == 1_600
    assert _lease_rows(path) == [(state.lease_id, RUN_LEASE_KIND, 1_600)]


def test_a_renewal_moves_the_deadline(
    published: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, run_id = published
    monkeypatch.setattr(_LEASE_CLOCK, lambda: 1_000)
    state = _acquire(tmp_path, run_id)
    monkeypatch.setattr(_LEASE_CLOCK, lambda: 5_000)

    renewed = renew_intent_run_lease(root=tmp_path, state=state)

    assert renewed.held
    assert renewed.expires_at == 5_600
    assert _lease_rows(path) == [(state.lease_id, RUN_LEASE_KIND, 5_600)]


def test_a_lease_not_held_is_not_retried_by_renewal(tmp_path: Path) -> None:
    refused = RunLeaseState(
        held=False,
        reason=SERVING_REASON_STORE_UNAVAILABLE,
        lease_id="intent:1:2:3:i",
        ttl_seconds=600,
    )

    assert renew_intent_run_lease(root=tmp_path, state=refused) is refused
    assert release_intent_run_lease(root=tmp_path, state=refused) is refused


def test_a_release_clears_the_grant(
    published: tuple[Path, str], tmp_path: Path
) -> None:
    path, run_id = published
    state = _acquire(tmp_path, run_id)

    released = release_intent_run_lease(root=tmp_path, state=state)

    assert not released.held
    assert released.reason == RUN_LEASE_RELEASED
    assert _lease_rows(path) == []


# ── every refusal, typed ─────────────────────────────────────────────────


def test_the_kill_switch_opens_no_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "never.sqlite3"
    monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED", raising=False)
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store))

    state = _acquire(tmp_path, "a" * 64)
    held = RunLeaseState(
        held=True,
        reason=RUN_LEASE_HELD,
        lease_id="intent:1:2:3:i",
        ttl_seconds=600,
        link=_linked("a" * 64),
        store_run_id="a" * 64,
        expires_at=1,
    )
    released = release_intent_run_lease(root=tmp_path, state=held)

    assert state.reason == SERVING_REASON_STORE_DISABLED
    assert released.reason == SERVING_REASON_STORE_DISABLED
    assert not store.exists()


def test_a_record_that_stored_nothing_is_not_leased(tmp_path: Path) -> None:
    unlinked = acquire_intent_run_lease(
        root=tmp_path, link=None, lease_id="intent:1:2:3:i", ttl_seconds=600
    )
    unpublished = acquire_intent_run_lease(
        root=tmp_path,
        link=RunSnapshotLink(
            state=RUN_SNAPSHOT_LINK_UNPUBLISHED,
            outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED,
        ),
        lease_id="intent:1:2:3:i",
        ttl_seconds=600,
    )

    assert (unlinked.reason, unlinked.detail) == (SERVING_REASON_NOT_PUBLISHED, "")
    assert (unpublished.reason, unpublished.detail) == (
        SERVING_REASON_NOT_PUBLISHED,
        RUN_SNAPSHOT_PUBLICATION_DISABLED,
    )


def test_a_missing_store_is_not_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "absent.sqlite3"
    _enable(monkeypatch, store)

    state = _acquire(tmp_path, "a" * 64)

    assert state.reason == SERVING_REASON_STORE_ABSENT
    assert not store.exists()


def test_a_run_the_store_no_longer_holds_is_typed(
    published: tuple[Path, str], tmp_path: Path
) -> None:
    state = _acquire(tmp_path, "f" * 64)

    assert not state.held
    assert state.reason == SERVING_REASON_RUN_NOT_PUBLISHED
    assert "not a published run" in state.detail


def test_a_lease_id_already_naming_another_grant_is_refused(
    published: tuple[Path, str], tmp_path: Path
) -> None:
    path, run_id = published
    with RunStore(path, create=False) as store:
        acquire_run_lease(
            store, run_id, kind="export", lease_id="intent:1:2:3:i", ttl_seconds=60
        )

    state = _acquire(tmp_path, run_id)

    assert state.reason == RUN_LEASE_REFUSED
    assert "already grants a different run or kind" in state.detail


def test_a_damaged_store_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "damaged.sqlite3"
    store.write_bytes(b"this is not a sqlite database" * 64)
    _enable(monkeypatch, store)

    assert _acquire(tmp_path, "a" * 64).reason == SERVING_REASON_INTEGRITY


def test_a_store_of_another_generation_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "generation-1.sqlite3"
    shutil.copyfile(_GENERATION_1 / "runs.sqlite3", store)
    _enable(monkeypatch, store)

    assert _acquire(tmp_path, "a" * 64).reason == SERVING_REASON_INCOMPATIBLE_GENERATION


def test_a_locked_store_is_typed_unavailable_on_grant_and_release(
    published: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, run_id = published
    monkeypatch.setattr(_BUSY_TIMEOUT, 50)
    held = _acquire(tmp_path, run_id)
    blocker = sqlite3.connect(path, timeout=0.1)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        granted = _acquire(tmp_path, run_id, lease_id="intent:1:2:4:j")
        released = release_intent_run_lease(root=tmp_path, state=held)
    finally:
        blocker.rollback()
        blocker.close()

    assert granted.reason == SERVING_REASON_STORE_UNAVAILABLE
    assert released.reason == SERVING_REASON_STORE_UNAVAILABLE
    # Left to its deadline: the grant the release could not reach is intact.
    assert [row[0] for row in _lease_rows(path)] == [held.lease_id]


# ── the write boundary: a lease is a write ────────────────────────────────


def _publish_into(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with RunStore(path) as store:
        return store.write_full_run(
            fixture_model(),
            namespace="lease-door",
            target="worktree",
            expected_generation=0,
        ).run_id


#: Where the store lies, relative to ``tmp_path`` whose ``repo`` is the root.
#: The prefix neighbour is the one a string-prefix test would admit.
_STORE_PLACES = (
    ("inside-codeclone", "repo/.codeclone/db/runs.sqlite3", True),
    ("outside-the-root", "outside/runs.sqlite3", False),
    ("prefix-sibling", "repo/.codeclone-x/runs.sqlite3", False),
    ("root-not-service", "repo/runs.sqlite3", False),
)


@pytest.mark.parametrize(
    ("place", "held"),
    [(place, held) for _id, place, held in _STORE_PLACES],
    ids=[case_id for case_id, _place, _held in _STORE_PLACES],
)
def test_a_lease_is_written_only_inside_the_service_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, place: str, held: bool
) -> None:
    """The same published run, the same link; only where the store lies
    differs.  Inside the root's ``.codeclone/`` the grant is written (the
    positive control); anywhere else nothing is, and the answer says why."""
    root = tmp_path / "repo"
    root.mkdir()
    store = tmp_path / place
    run_id = _publish_into(store)
    _enable(monkeypatch, store)

    state = _acquire(root, run_id)

    assert state.held is held, state
    if held:
        assert _lease_rows(store) == [
            (state.lease_id, RUN_LEASE_KIND, state.expires_at)
        ]
        return
    assert state.reason == SERVING_REASON_STORE_DISABLED, state
    assert "outside CodeClone's service directories" in state.detail, state
    assert _lease_rows(store) == []


# ── the vocabulary and the id ─────────────────────────────────────────────


def test_a_lease_id_names_the_session_the_sequence_and_the_intent() -> None:
    first = run_lease_id(
        agent_pid=11, agent_start_epoch=100, sequence=1, intent_id="intent-ab-001"
    )

    assert first == "intent:11:100:1:intent-ab-001"
    assert first != run_lease_id(
        agent_pid=12, agent_start_epoch=100, sequence=1, intent_id="intent-ab-001"
    )
    assert first != run_lease_id(
        agent_pid=11, agent_start_epoch=101, sequence=1, intent_id="intent-ab-001"
    )
    assert first != run_lease_id(
        agent_pid=11, agent_start_epoch=100, sequence=2, intent_id="intent-ab-001"
    )


@pytest.mark.parametrize(
    ("held", "reason", "expires_at"),
    [
        (True, "no-such-reason", 1),
        (True, SERVING_REASON_STORE_DISABLED, 1),
        (False, RUN_LEASE_HELD, None),
        (False, SERVING_REASON_STORE_DISABLED, 1),
    ],
)
def test_a_lease_state_is_one_of_the_closed_shapes(
    held: bool, reason: str, expires_at: int | None
) -> None:
    with pytest.raises(ValueError):
        RunLeaseState(
            held=held,
            reason=reason,
            lease_id="intent:1:2:3:i",
            ttl_seconds=600,
            expires_at=expires_at,
        )


def test_the_reason_vocabulary_is_closed() -> None:
    """The lease's own three words and the serving road's reasons for not
    reaching a run; a word added on either side reds here."""
    assert RUN_LEASE_REASONS == (
        RUN_LEASE_HELD,
        SERVING_REASON_INCOMPATIBLE_GENERATION,
        SERVING_REASON_INTEGRITY,
        RUN_LEASE_REFUSED,
        SERVING_REASON_NOT_PUBLISHED,
        RUN_LEASE_RELEASED,
        SERVING_REASON_RUN_NOT_PUBLISHED,
        SERVING_REASON_STORE_ABSENT,
        SERVING_REASON_STORE_DISABLED,
        SERVING_REASON_STORE_UNAVAILABLE,
        "unexpressible",
    )
