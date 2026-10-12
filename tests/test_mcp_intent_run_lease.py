# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A live intent's before-run is held in the run store by a session lease.

The store's collector keeps a target's head and one previous generation, then
whatever a lease or a retention row roots.  Before this lease nothing rooted
the run a live change intent was declared against, so two later publications
of the same root collected it while the cycle was still open.

Driven here end to end, on a temporary repository with its own store and the
rollout switched on inside the test (never a production store):

* the garbage-collector probe and its positive control -- the same three
  publications collect the first run when its lease is released, and leave it
  and its report link in place while the intent holds the lease;
* the lease's lifecycle points: start / promote / recover take it, renewal
  re-grants it, clear / supersession release it, a queued intent holds none,
  a retired intent keeps it;
* the lease never decides a cycle: the rollout off, a damaged store -- start
  stays active and the answers carry no lease field;
* two servers on one root hold two grants and release only their own.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.api.intent_run_lease import RUN_LEASE_HELD, RUN_LEASE_KIND, RunLeaseState
from codeclone.api.run_store_serving import (
    SERVING_REASON_INTEGRITY,
    SERVING_REASON_NOT_PUBLISHED,
    SERVING_REASON_STORE_DISABLED,
)
from codeclone.surfaces.mcp._workspace_intents import (
    WorkspaceIntentRecord,
    compute_scope_digest,
    expires_at,
    find_workspace_intent,
    format_utc,
    remove_workspace_record,
    utc_now,
    write_workspace_intent,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest
from tests._run_store_paths import run_store_service_path

_PID_ALIVE = "codeclone.surfaces.mcp._workspace_intent_pid.is_agent_pid_alive"


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
class _Repo:
    root: Path
    store: Path
    service: CodeCloneMCPService

    def write(self, functions: int) -> None:
        """A tree whose analysed content -- and so its stored run -- differs
        for every distinct ``functions``."""
        body = "".join(
            f"def f{n}(x: int) -> int:\n    return x + {n}\n\n"
            for n in range(functions)
        )
        self.root.joinpath("pkg", "a.py").write_text(body, "utf-8")

    def analyze(self) -> str:
        summary = self.service.analyze_repository(
            MCPAnalysisRequest(root=str(self.root), respect_pyproject=False)
        )
        return str(summary["run_id"])

    def start(self, scope: list[str] | None = None) -> str:
        started = self.service.start_controlled_change(
            root=str(self.root),
            scope={"allowed_files": scope or ["pkg/a.py"]},
            intent="edit pkg.a",
        )
        assert started["status"] == "active", started
        return str(started["intent_id"])

    def latest_store_run_id(self) -> str:
        link = self.service._runs.records()[-1].execution.run_snapshot_link
        assert link is not None
        assert link.store_run_id
        return link.store_run_id

    def lease(self, intent_id: str) -> RunLeaseState | None:
        return _lease_of(self.service, intent_id)

    def _rows(self, sql: str, *args: object) -> list[tuple[object, ...]]:
        connection = sqlite3.connect(f"file:{self.store}?mode=ro", uri=True)
        try:
            return list(connection.execute(sql, args).fetchall())
        finally:
            connection.close()

    def run_held(self, store_run_id: str) -> bool:
        return bool(self._rows("SELECT 1 FROM runs WHERE run_id = ?", store_run_id))

    def links_of(self, store_run_id: str) -> int:
        (count,) = self._rows(
            "SELECT count(*) FROM run_report_links l "
            "JOIN runs r ON r.run_pk = l.run_pk WHERE r.run_id = ?",
            store_run_id,
        )[0]
        return int(str(count))

    def lease_rows(self) -> list[tuple[str, str, str]]:
        return [
            (str(lease_id), str(kind), str(run_id))
            for lease_id, kind, run_id in self._rows(
                "SELECT l.lease_id, l.kind, r.run_id FROM run_leases l "
                "JOIN runs r ON r.run_pk = l.run_pk ORDER BY l.lease_id"
            )
        ]


def _lease_of(service: CodeCloneMCPService, intent_id: str) -> RunLeaseState | None:
    """Where part two reads an intent's lease state: the session's map."""
    entry = service._intent_run_leases.get(intent_id)
    return None if entry is None else entry[1]


def _commit_all(root: Path) -> None:
    for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "init")):
        _git(root, *args)


def _enable(monkeypatch: pytest.MonkeyPatch, store: Path) -> None:
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store))


def _new_repo(tmp_path: Path, name: str = "repo") -> tuple[Path, Path]:
    root = tmp_path / name
    root.joinpath("pkg").mkdir(parents=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("README.md").write_text("stable\n", "utf-8")
    # The root's own store: MCP writes a run store, and takes a lease in one,
    # only inside the root's ``.codeclone/`` (its write boundary).
    return root, run_store_service_path(root)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Repo]:
    root, store = _new_repo(tmp_path)
    _enable(monkeypatch, store)
    state = _Repo(root=root, store=store, service=CodeCloneMCPService())
    state.write(1)
    _commit_all(root)
    state.analyze()
    yield state


# ── the collector ─────────────────────────────────────────────────────────


def _publish_three_more(repo: _Repo) -> tuple[str, str, str]:
    """Three later publications of new content on the same root and target.

    Three, not two: the collector keeps the head and one previous
    generation, so the second publication is the one that would first
    collect the first run, and the third is the one that collects the
    second -- the witness that the sweep ran and chose its victims, rather
    than aborting.  (A leased run is also guarded by the store's foreign
    keys; a sweep that ignored the lease would try to delete it, be refused,
    and roll back without collecting anything.)
    """
    published = []
    for functions in (2, 3, 4):
        repo.write(functions)
        repo.analyze()
        published.append(repo.latest_store_run_id())
    second, third, fourth = published
    return second, third, fourth


def test_positive_control_without_the_lease_the_publications_collect_the_run(
    repo: _Repo,
) -> None:
    first = repo.latest_store_run_id()
    intent_id = repo.start()
    # The one difference from the probe below: the lease is released.
    repo.service._release_intent_run_leases([intent_id])
    assert repo.lease_rows() == []

    second, third, fourth = _publish_three_more(repo)

    # Four publications, four runs: the population holds the case.
    assert len({first, second, third, fourth}) == 4
    assert not repo.run_held(first)
    assert not repo.run_held(second)
    assert repo.run_held(third)
    assert repo.run_held(fourth)


def test_a_leased_before_run_survives_the_publications_until_clear(
    repo: _Repo,
) -> None:
    first = repo.latest_store_run_id()
    assert repo.links_of(first) == 1
    intent_id = repo.start()

    second, third, fourth = _publish_three_more(repo)

    assert len({first, second, third, fourth}) == 4
    # The sweep ran and chose: the unleased second run went, the leased
    # first one and its report link stayed.
    assert not repo.run_held(second)
    assert repo.run_held(first)
    assert repo.links_of(first) == 1
    assert repo.run_held(third)
    assert repo.run_held(fourth)
    lease = repo.lease(intent_id)
    assert lease is not None
    assert lease.held

    repo.service.manage_change_intent(action="clear", intent_id=intent_id)
    assert repo.lease_rows() == []
    repo.write(5)
    repo.analyze()

    assert not repo.run_held(first)
    assert repo.links_of(first) == 0


# ── the lifecycle ─────────────────────────────────────────────────────────


def test_start_holds_a_session_lease_on_the_before_run(repo: _Repo) -> None:
    first = repo.latest_store_run_id()

    intent_id = repo.start()

    lease = repo.lease(intent_id)
    assert lease is not None
    assert lease.reason == RUN_LEASE_HELD
    assert lease.store_run_id == first
    service = repo.service
    assert lease.lease_id.startswith(
        f"intent:{service._agent_pid}:{service._agent_start_epoch}:"
    )
    assert lease.lease_id.endswith(f":{intent_id}")
    assert repo.lease_rows() == [(lease.lease_id, RUN_LEASE_KIND, first)]


def test_an_accepted_finish_releases_the_lease(repo: _Repo) -> None:
    intent_id = repo.start(["README.md"])
    repo.root.joinpath("README.md").write_text("changed\n", "utf-8")

    finished = repo.service.finish_controlled_change(
        intent_id=intent_id,
        changed_files=["README.md"],
    )

    assert finished["intent_cleared"] is True
    assert repo.lease_rows() == []
    assert repo.lease(intent_id) is None


def test_superseding_releases_the_superseded_lease(repo: _Repo) -> None:
    first_intent = repo.start()
    first_lease = repo.lease(first_intent)
    assert first_lease is not None

    replaced = repo.service.manage_change_intent(
        action="declare",
        root=str(repo.root),
        scope={"allowed_files": ["pkg/a.py"]},
        intent="declare again",
    )

    second_lease = repo.lease(str(replaced["intent_id"]))
    assert second_lease is not None
    assert repo.lease(first_intent) is None
    assert [row[0] for row in repo.lease_rows()] == [second_lease.lease_id]


def _foreign_overlap(root: Path, run_id: str) -> WorkspaceIntentRecord:
    now = utc_now()
    scope: dict[str, object] = {
        "allowed_files": ["pkg/a.py"],
        "allowed_related": [],
        "forbidden": [],
    }
    record = WorkspaceIntentRecord(
        intent_id="intent-foreign-001",
        agent_pid=99999,
        agent_start_epoch=1000000,
        agent_label="agent-a",
        run_id=run_id,
        declared_at_utc=format_utc(now),
        expires_at_utc=expires_at(declared_at=now, ttl_seconds=3600),
        ttl_seconds=3600,
        status="active",
        intent="agent A edits pkg/a",
        scope=scope,
        scope_digest=compute_scope_digest(scope),
        blast_radius_summary={},
        lease_renewed_at_utc=format_utc(now),
        lease_seconds=300,
        report_digest="foreign-digest",
    )
    write_workspace_intent(root=root, record=record)
    return record


def test_a_queued_intent_holds_no_lease_and_promote_takes_one(
    repo: _Repo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PID_ALIVE, lambda _pid: True)
    run_id = repo.service._runs.records()[-1].run_id
    foreign = _foreign_overlap(repo.root, run_id)
    queued = repo.service.manage_change_intent(
        action="declare",
        root=str(repo.root),
        scope={"allowed_files": ["pkg/a.py"]},
        intent="wait for pkg/a",
        on_conflict="queue",
        ttl_seconds=120,
    )
    assert queued["status"] == "queued"
    queued_id = str(queued["intent_id"])
    assert repo.lease(queued_id) is None
    assert repo.lease_rows() == []

    remove_workspace_record(root=repo.root, record=foreign)
    promoted = repo.service.manage_change_intent(
        action="promote",
        intent_id=queued_id,
    )

    assert promoted["status"] == "active"
    lease = repo.lease(queued_id)
    assert lease is not None
    assert lease.held
    # The lease lasts as long as the intent: its TTL is read off its row.
    assert lease.ttl_seconds == 120
    assert [row[0] for row in repo.lease_rows()] == [lease.lease_id]


def _start_and_retire(repo: _Repo) -> tuple[str, RunLeaseState, str]:
    """Start an intent, then lose its before-run from memory: the intent is
    retired and keeps its lease.  Returns the intent id, its lease and the
    run id an unchanged tree analyses to."""
    intent_id = repo.start()
    before = repo.lease(intent_id)
    assert before is not None
    bound = repo.service._active_intents[intent_id].before_execution_id
    assert bound is not None
    repo.analyze()
    repo.service._runs.unpin_execution(bound)
    run_id = repo.analyze()
    assert intent_id in repo.service._before_run_evicted_intents
    return intent_id, before, run_id


def _recover(repo: _Repo, intent_id: str, run_id: str) -> RunLeaseState:
    recovered = repo.service.manage_change_intent(
        action="recover",
        root=str(repo.root),
        run_id=run_id,
        intent_id=intent_id,
    )
    assert recovered["action_taken"] == "recovered", recovered
    after = repo.lease(intent_id)
    assert after is not None
    assert after.held
    return after


def test_a_retired_intent_keeps_its_lease_and_recover_rebinds_it(
    repo: _Repo,
) -> None:
    intent_id, before, run_id = _start_and_retire(repo)
    # Memory lost the run; the store still holds it, for part two to serve.
    assert repo.lease(intent_id) == before
    assert [row[0] for row in repo.lease_rows()] == [before.lease_id]

    after = _recover(repo, intent_id, run_id)

    assert after.lease_id != before.lease_id
    assert [row[0] for row in repo.lease_rows()] == [after.lease_id]


def test_a_rebinding_takes_the_new_lease_before_it_releases_the_old_one(
    repo: _Repo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover rebinds a retired intent to the same stored run.  Between the
    two grants the run must stay rooted: the new lease is in the store when
    the old one is released, never after."""
    from codeclone.api.intent_run_lease import acquire_intent_run_lease as acquire
    from codeclone.api.intent_run_lease import release_intent_run_lease as release

    stored = repo.latest_store_run_id()
    intent_id, before, run_id = _start_and_retire(repo)
    # The population holds the case: the rebinding names the same run.
    assert repo.latest_store_run_id() == stored
    calls: list[tuple[str, str, list[tuple[str, str, str]]]] = []

    def _acquire(**kwargs: object) -> RunLeaseState:
        calls.append(("acquire", str(kwargs["lease_id"]), repo.lease_rows()))
        return acquire(**kwargs)  # type: ignore[arg-type]

    def _release(*, root: Path, state: RunLeaseState) -> None:
        calls.append(("release", state.lease_id, repo.lease_rows()))
        release(root=root, state=state)

    mixin = "codeclone.surfaces.mcp._session_run_lease_mixin"
    monkeypatch.setattr(f"{mixin}.acquire_intent_run_lease", _acquire)
    monkeypatch.setattr(f"{mixin}.release_intent_run_lease", _release)

    after = _recover(repo, intent_id, run_id)

    assert [(kind, lease_id) for kind, lease_id, _rows in calls] == [
        ("acquire", after.lease_id),
        ("release", before.lease_id),
    ]
    # At the moment the old grant is released, the new one already roots
    # the run they both name.
    released_while = calls[1][2]
    assert (after.lease_id, RUN_LEASE_KIND, stored) in released_while
    assert (before.lease_id, RUN_LEASE_KIND, stored) in released_while
    assert repo.lease_rows() == [(after.lease_id, RUN_LEASE_KIND, stored)]


@pytest.mark.parametrize(
    ("action", "extra"),
    [
        ("renew", {}),
        ("get", {}),
        ("check", {"changed_files": ["pkg/a.py"]}),
    ],
)
def test_the_lease_is_renewed_where_the_intent_lease_is(
    repo: _Repo,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    extra: dict[str, object],
) -> None:
    from codeclone.api.intent_run_lease import renew_intent_run_lease as real

    intent_id = repo.start()
    renewed: list[str] = []

    def _spy(*, root: Path, state: RunLeaseState) -> RunLeaseState:
        renewed.append(state.lease_id)
        return real(root=root, state=state)

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._session_run_lease_mixin.renew_intent_run_lease",
        _spy,
    )

    repo.service.manage_change_intent(action=action, intent_id=intent_id, **extra)

    lease = repo.lease(intent_id)
    assert lease is not None
    assert renewed == [lease.lease_id]
    assert lease.held


def test_two_servers_on_one_root_hold_and_release_only_their_own(
    repo: _Repo,
) -> None:
    other = CodeCloneMCPService()
    other._agent_pid = repo.service._agent_pid + 1
    other._agent_start_epoch = repo.service._agent_start_epoch + 1
    other.analyze_repository(
        MCPAnalysisRequest(root=str(repo.root), respect_pyproject=False)
    )
    mine = repo.start(["pkg/a.py"])
    theirs = str(
        other.start_controlled_change(
            root=str(repo.root),
            scope={"allowed_files": ["README.md"]},
            intent="edit the readme",
        )["intent_id"]
    )
    my_lease = repo.lease(mine)
    their_lease = _lease_of(other, theirs)
    assert my_lease is not None
    assert their_lease is not None
    assert my_lease.lease_id != their_lease.lease_id
    assert len(repo.lease_rows()) == 2

    repo.service.manage_change_intent(action="clear", intent_id=mine)

    assert [row[0] for row in repo.lease_rows()] == [their_lease.lease_id]


# ── the lease never decides a cycle ───────────────────────────────────────


def test_with_the_rollout_off_start_is_unchanged_and_no_store_appears(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED", raising=False)
    monkeypatch.delenv("CODECLONE_RUN_STORE_FORCE", raising=False)
    monkeypatch.delenv("CODECLONE_RUN_STORE_PATH", raising=False)
    root, store = _new_repo(tmp_path)
    off = _Repo(root=root, store=store, service=CodeCloneMCPService())
    off.write(1)
    _commit_all(root)
    off.analyze()

    intent_id = off.start()

    lease = off.lease(intent_id)
    assert lease is not None
    assert not lease.held
    # Nothing was stored, so there is nothing to lease: the same reason the
    # serving door gives a record that published nothing.
    assert (lease.reason, lease.detail) == (SERVING_REASON_NOT_PUBLISHED, "disabled")
    assert not root.joinpath(".codeclone", "db", "runs.sqlite3").exists()
    assert not store.exists()


def test_a_damaged_store_does_not_fail_start(repo: _Repo) -> None:
    repo.store.write_bytes(b"this is not a sqlite database" * 64)

    intent_id = repo.start()

    lease = repo.lease(intent_id)
    assert lease is not None
    assert not lease.held
    assert lease.reason == SERVING_REASON_INTEGRITY


def test_the_start_answer_carries_no_lease(
    repo: _Repo,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = repo.service.start_controlled_change(
        root=str(repo.root),
        scope={"allowed_files": ["pkg/a.py"]},
        intent="edit pkg.a",
    )
    monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED")
    root, store = _new_repo(tmp_path, "off")
    off = _Repo(root=root, store=store, service=CodeCloneMCPService())
    off.write(1)
    _commit_all(root)
    off.analyze()
    unleased = off.service.start_controlled_change(
        root=str(root),
        scope={"allowed_files": ["pkg/a.py"]},
        intent="edit pkg.a",
    )

    held = repo.lease(str(started["intent_id"]))
    assert held is not None
    assert held.held
    assert sorted(started) == sorted(unleased)
    assert "run_lease" not in str(started)


def test_the_kill_switch_turned_off_after_publication_takes_no_lease(
    repo: _Repo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODECLONE_RUN_STORE_ENABLED")

    intent_id = repo.start()

    lease = repo.lease(intent_id)
    assert lease is not None
    assert lease.reason == SERVING_REASON_STORE_DISABLED
    assert repo.lease_rows() == []


def test_a_renewal_never_brings_back_a_lease_released_meanwhile(
    repo: _Repo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.api.intent_run_lease import renew_intent_run_lease as real

    intent_id = repo.start()

    def _cleared_while_renewing(*, root: Path, state: RunLeaseState) -> RunLeaseState:
        # Another call clears the intent while this renewal talks to the store.
        repo.service._release_intent_run_leases([intent_id])
        return real(root=root, state=state)

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._session_run_lease_mixin.renew_intent_run_lease",
        _cleared_while_renewing,
    )

    repo.service.manage_change_intent(action="renew", intent_id=intent_id)

    assert repo.lease(intent_id) is None


def test_the_lease_ttl_falls_back_to_the_configured_default(
    repo: _Repo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.mcp._session_run_lease_mixin import _registry_ttl_seconds
    from codeclone.surfaces.mcp._workspace_intent_store import (
        WorkspaceIntentRegistryUnreadableError,
    )

    monkeypatch.setenv("CODECLONE_INTENT_TTL_SECONDS", "240")
    assert _registry_ttl_seconds(repo.root, "intent-never-declared-001") == 240

    def _unreadable(**_kwargs: object) -> None:
        raise WorkspaceIntentRegistryUnreadableError(
            backend="file", storage_path=repo.root, error="PermissionError: denied"
        )

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._session_run_lease_mixin.find_workspace_intent",
        _unreadable,
    )
    assert _registry_ttl_seconds(repo.root, "intent-never-declared-001") == 240


def test_a_workspace_renewal_the_registry_refused_renews_no_store_lease(
    repo: _Repo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent_id = repo.start()
    renewed: list[str] = []

    def _spy(*, root: Path, state: RunLeaseState) -> RunLeaseState:
        renewed.append(state.lease_id)
        return state

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._session_run_lease_mixin.renew_intent_run_lease",
        _spy,
    )
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._session_intent_mixin.renew_workspace_intent_lease",
        lambda **_kwargs: False,
    )

    repo.service.manage_change_intent(action="renew", intent_id=intent_id)
    repo.service.manage_change_intent(action="get", intent_id=intent_id)

    assert renewed == []


def test_shutdown_releases_the_sessions_store_leases(repo: _Repo) -> None:
    repo.start()
    assert len(repo.lease_rows()) == 1

    repo.service.shutdown_cleanup()

    assert repo.lease_rows() == []


def test_clear_session_runs_forgets_retired_intents_and_releases_every_lease(
    repo: _Repo,
) -> None:
    retired_id, _before, _run_id = _start_and_retire(repo)
    active_id = repo.start(["README.md"])
    assert len(repo.lease_rows()) == 2

    cleared = repo.service.clear_session_runs()

    assert cleared["cleared_intents"] == 2
    assert cleared["workspace_cleared"] is True
    assert repo.lease_rows() == []
    assert repo.service._intent_run_leases == {}
    assert repo.service._before_run_evicted_intents == {}
    for intent_id in (retired_id, active_id):
        assert find_workspace_intent(root=repo.root, intent_id=intent_id) is None


def test_an_intent_id_handed_out_again_after_clear_starts_clean(
    repo: _Repo,
) -> None:
    retired_id, _before, _run_id = _start_and_retire(repo)
    repo.service.clear_session_runs()
    repo.analyze()

    reused = repo.start()

    # Intent ids restart with the session's runs: the same id, a new intent,
    # with nothing of the one that wore it before.
    assert reused == retired_id
    assert reused not in repo.service._before_run_evicted_intents
    lease = repo.lease(reused)
    assert lease is not None
    assert lease.held
    assert [row[0] for row in repo.lease_rows()] == [lease.lease_id]
