# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A finish that cannot write memory must not cost the intent.

``finish_controlled_change`` runs two memory side effects -- the optional
``propose_memory`` proposal and the projection-rebuild enqueue -- and both open
the engineering memory store. When that store's schema is not the one this
executable implements, both raise. Measured 2026-09-08: with the auto-clear
running BEFORE them, the exception escaped a finish that had already removed the
intent, and two intents were lost that way. Losing an active intent is
control-plane state loss, heavier than the schema drift that caused it.

Two independent properties are pinned here, each by its own test, so a
regression in either is visible on its own:

- DURABILITY (``...keeps_the_intent``): however the refusal is shaped, the
  intent must still be addressable afterwards. Moving the clear back before the
  fallible hooks reddens this one and leaves the typed-ness test green.
- TYPED-NESS (``...is_a_typed_refusal...``): the refusal is a returned payload
  with an explicit reason, not an escaping exception. Removing the ``except``
  reddens this one and leaves the durability test green.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import cast

import pytest

import codeclone.surfaces.mcp._workspace_hygiene as mcp_workspace_hygiene_mod
from codeclone.surfaces.mcp._session_memory_mixin import MemorySchemaError
from codeclone.surfaces.mcp._session_shared import MCPServiceContractError
from codeclone.surfaces.mcp._workspace_hygiene import WorkspaceHygieneResult
from codeclone.surfaces.mcp._workspace_intent_store import get_workspace_intent_store
from codeclone.surfaces.mcp._workspace_intents import (
    WorkspaceIntentLifecycle,
    update_workspace_intent_status,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService

from .memory_fixtures import cli_memory_repo, memory_project_db_paths
from .memory_fixtures import stamp_engineering_memory_schema_version as _stamp
from .test_mcp_service import (
    _patch_contract_run_record,
    _recover_with_dead_pid,
    _seed_docs_intent,
    _stale_workspace_intent,
)

_OLD_SCHEMA = "1.7"
_REASON = "memory_schema_incompatible"

_ACCEPTED_VERIFY: dict[str, object] = {
    "status": "accepted",
    "reason": None,
    "verification_profile": "documentation_only",
    "structural_delta": {"verdict": "stable", "health_delta": 0, "regressions": []},
    "worsened": [],
    "claim_validation_recommended": False,
}


def _schema_refusal(**_: object) -> dict[str, object]:
    """Stand-in for a memory hook that meets an unreadable store.

    Raises the exact type ``codeclone.memory.sqlite_store`` raises through
    ``SqliteEngineeringMemoryStore(...)``; that this is the real type on the
    real path is proved separately by
    ``test_finish_propose_memory_really_raises_on_an_old_store``, so these
    pins stand for a mechanism that exists rather than an invented one.
    """
    raise MemorySchemaError(
        "Engineering memory schema is '1.7' on disk; this checkout expects '1.9'."
    )


def _clean_hygiene(**_: object) -> WorkspaceHygieneResult:
    return WorkspaceHygieneResult(
        git_available=True,
        dirty_paths=("README.md",),
        dirty_paths_in_scope=("README.md",),
        dirty_paths_outside_scope=(),
        foreign_dirty_overlaps=(),
        blocks_edit=False,
    )


def _finishable_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str,
    digest: str,
) -> tuple[CodeCloneMCPService, str]:
    """A service with one README-scoped intent whose verification accepts.

    Verification and hygiene are stubbed so the finish reaches its memory side
    effects deterministically; nothing about the intent lifecycle, the clear, or
    the memory hooks is stubbed -- those are what is under test.
    """
    service, intent_id = _seed_docs_intent(tmp_path, run_id=run_id, digest=digest)
    monkeypatch.setattr(service, "_patch_contract_verify", lambda **_: _ACCEPTED_VERIFY)
    monkeypatch.setattr(
        mcp_workspace_hygiene_mod, "finish_hygiene_check", _clean_hygiene
    )
    return service, intent_id


def _finish(service: CodeCloneMCPService, intent_id: str) -> dict[str, object]:
    return service.finish_controlled_change(
        intent_id=intent_id,
        changed_files=["README.md"],
        create_receipt=False,
        auto_clear=True,
        propose_memory=True,
    )


def _refusing_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str,
    digest: str,
) -> tuple[CodeCloneMCPService, str]:
    """A finishable service whose memory proposal always meets an unreadable store.

    Every test below starts here, so the ONE thing that differs between them is
    what each does with the finish afterwards -- not how the refusal was set up.
    """
    service, intent_id = _finishable_service(
        tmp_path, monkeypatch, run_id=run_id, digest=digest
    )
    monkeypatch.setattr(service, "finish_propose_memory", _schema_refusal)
    return service, intent_id


def _refused_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str,
    digest: str,
) -> tuple[CodeCloneMCPService, str]:
    """Drive one finish all the way to the typed schema refusal, and check it.

    For the recovery-square tests, whose subject is what happens AFTER a
    refusal; the refusal itself is asserted here so those tests never build on
    a finish that quietly succeeded.
    """
    service, intent_id = _refusing_service(
        tmp_path, monkeypatch, run_id=run_id, digest=digest
    )
    refused = _finish(service, intent_id)
    assert refused["reason"] == _REASON
    return service, intent_id


def test_finish_with_unreadable_memory_store_keeps_the_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DURABILITY. The intent survives, whatever shape the refusal took.

    The exception is tolerated here on purpose: this test answers only "does
    the intent still exist", so it stays green when the refusal is untyped and
    red only when authority was released before the fallible step.
    """
    service, intent_id = _refusing_service(
        tmp_path, monkeypatch, run_id="memschema12345678", digest="mem-schema-digest"
    )

    with contextlib.suppress(MemorySchemaError):
        _finish(service, intent_id)

    reachable = service.manage_change_intent(action="get", intent_id=intent_id)
    assert reachable["intent_id"] == intent_id

    row = get_workspace_intent_store(tmp_path).find_raw(intent_id)
    assert row is not None, "the workspace row must survive a refused finish"


def test_finish_with_unreadable_memory_store_is_a_typed_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TYPED-NESS. A returned payload with an explicit reason, not an escape.

    Says nothing about whether the intent survived -- that is the durability
    test's job -- so it stays green when the clear is misordered and red only
    when the refusal stops being typed.
    """
    service, intent_id = _refusing_service(
        tmp_path, monkeypatch, run_id="memtyped112345678", digest="mem-typed-digest"
    )

    finished = _finish(service, intent_id)

    memory_error = cast("dict[str, object]", finished["memory_error"])
    # One comparison, so a partial refusal cannot pass by satisfying some of it.
    # The last member is the "nothing was proposed" claim: no memory candidates.
    assert (
        finished["status"],
        finished["reason"],
        finished["intent_cleared"],
        finished["user_action_required"],
        memory_error["error"],
        "memory_candidates" in finished,
    ) == ("unverified", _REASON, False, True, _REASON, False)
    for needle, haystack in (
        (_OLD_SCHEMA, memory_error["message"]),
        ("finish_controlled_change again", finished["next_step"]),
    ):
        assert needle in str(haystack), f"{needle!r} missing from {haystack!r}"


def test_refused_finish_marks_the_registry_row_needs_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A third property, deliberately kept out of the two boundary pins.

    The registry row must carry the fate the response names -- "recover me",
    not "editing normally" -- so a later session reading the registry sees what
    the agent was told. Both boundary mutations disturb this one, which is
    exactly why it does not live inside either of them: mixing it in would make
    one mutation redden both pins and stop separating the two failures.
    """
    service, intent_id = _refusing_service(
        tmp_path, monkeypatch, run_id="memrecov112345678", digest="mem-recov-digest"
    )

    _finish(service, intent_id)

    row = get_workspace_intent_store(tmp_path).find_raw(intent_id)
    assert row is not None
    assert row.status == WorkspaceIntentLifecycle.NEEDS_RECOVERY.value


def test_finish_succeeds_exactly_once_after_the_store_becomes_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery square, cases 2 and 3: readable, then finished exactly once."""
    service, intent_id = _refused_finish(
        tmp_path, monkeypatch, run_id="memretry112345678", digest="mem-retry-digest"
    )

    # Case 2: the intent is READABLE across the failure.
    assert (
        service.manage_change_intent(action="get", intent_id=intent_id)["intent_id"]
        == intent_id
    )

    # The executable becomes compatible with the store.
    monkeypatch.setattr(
        service, "finish_propose_memory", lambda **_: {"memory_candidates": []}
    )
    monkeypatch.setattr(
        service, "maybe_auto_enqueue_projection_rebuild", lambda **_: None
    )

    # Case 3: the retry finishes...
    retried = _finish(service, intent_id)
    assert retried["status"] == "accepted"
    assert retried["intent_cleared"] is True

    # ...exactly once. A second retry has nothing left to finish.
    with pytest.raises(MCPServiceContractError):
        _finish(service, intent_id)


def test_stale_owner_is_fenced_out_after_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery square, case 4: the pre-restart owner may not move the row.

    Reported as an accounting rather than a bare verdict: the SAME call is
    made twice against the SAME row, once as the stale owner and once as the
    recovered owner. A refusal coming from anywhere other than the fencing
    pair would show up as both calls failing, which the assertion would name.
    """
    service, intent_id = _refused_finish(
        tmp_path, monkeypatch, run_id="memfence112345678", digest="mem-fence-digest"
    )
    stale_pid = service._agent_pid
    stale_epoch = service._agent_start_epoch

    # The intent outlives its owner: lease expired, owning process gone.
    _stale_workspace_intent(tmp_path, intent_id=intent_id)
    restarted = CodeCloneMCPService(history_limit=4)
    restarted._agent_start_epoch = stale_epoch + 1000
    restarted._runs.register(
        _patch_contract_run_record(
            tmp_path,
            run_id="memfence112345678",
            digest="mem-fence-digest",
            include_regression=False,
            complexity=6,
            health=90,
        )
    )
    recovered = _recover_with_dead_pid(
        monkeypatch,
        restarted,
        root=tmp_path,
        intent_id=intent_id,
        run_id="memfence",
    )
    assert recovered["action_taken"] == "recovered", recovered

    fenced = update_workspace_intent_status(
        root=tmp_path,
        pid=stale_pid,
        start_epoch=stale_epoch,
        intent_id=intent_id,
        new_status=WorkspaceIntentLifecycle.CLOSED.value,
    )
    owner = update_workspace_intent_status(
        root=tmp_path,
        pid=restarted._agent_pid,
        start_epoch=restarted._agent_start_epoch,
        intent_id=intent_id,
        new_status=WorkspaceIntentLifecycle.ACTIVE.value,
    )
    assert (fenced, owner) == (False, True), (
        "stale owner must be refused and the recovered owner accepted; "
        f"got stale={fenced} recovered={owner}"
    )


def test_finish_propose_memory_really_raises_on_an_old_store(tmp_path: Path) -> None:
    """Probe validity: the stubbed refusal above stands for a real one.

    Not a stub anywhere in the chain -- a real store, stamped at an older
    schema, opened by the real ``finish_propose_memory``. Without this, the
    monkeypatched tests would only prove that finish handles an exception
    somebody invented.
    """
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, store):
        store.close()
        _project2, db_path = memory_project_db_paths(root)
        _stamp(db_path, version=_OLD_SCHEMA)
        service = CodeCloneMCPService(history_limit=2)
        with pytest.raises(MemorySchemaError) as excinfo:
            service.finish_propose_memory(
                root_path=root,
                changed_files=["pkg/mod.py"],
                claims_text=None,
                review_text=None,
                verification_profile="documentation_only",
            )
    assert _OLD_SCHEMA in str(excinfo.value)
