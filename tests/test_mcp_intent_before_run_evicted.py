# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""An intent whose before-run the server stopped holding is never lost silently.

The server holds a bounded number of runs in memory.  An active intent pins
the execution it was declared against, but a pin can still go: the pin
ceiling releases the oldest, and a queued intent holds none.  Once the
execution is gone, the next analysis used to drop the intent from the session
without a trace -- no audit event, the workspace registry row left saying
``active`` -- and every later call on it answered ``Unknown change intent
id``; a call that came before that analysis met the raw run miss instead.

Pinned here, on real analyses of a temporary repository:

* the intent stays known, retired as ``before_run_evicted``, until it is
  cleared or recovered, with one audit event and its registry row moved to
  ``needs_recovery``;
* ``finish`` / ``get`` / ``check`` / ``renew`` answer that one reason word
  with a next step whose every named action exists, and that next step is
  walked to an accepted finish (recover) or to a fresh start (clear);
* the outcomes that were already typed keep their bytes: ``promote`` on a
  queued intent, the atomic verify's ``no_before_run``, a queued intent's
  ``intent_not_active``;
* a declare that supersedes an intent releases that intent's pin, and never
  a pin a queued intent did not hold.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import pytest

from codeclone.surfaces.mcp._intent import IntentStatus
from codeclone.surfaces.mcp._session_shared import (
    MAX_PINNED_MCP_RUNS,
    MCPRunNotFoundError,
    MCPServiceContractError,
)
from codeclone.surfaces.mcp._workspace_intents import find_workspace_intent
from codeclone.surfaces.mcp.messages import intent as intent_msgs
from codeclone.surfaces.mcp.messages import patch_contract as patch_msgs
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest

REASON = "before_run_evicted"
# The audit vocabulary is closed; a retirement reuses the intent event whose
# trajectory reading is "abandoned unless a later finish accepted".
INTENT_EXPIRED_EVENT = "intent.expired"


class _AuditRow(Protocol):
    @property
    def event_type(self) -> str: ...
    @property
    def severity(self) -> str: ...
    @property
    def intent_id(self) -> str | None: ...
    @property
    def status(self) -> str | None: ...
    @property
    def payload(self) -> Mapping[str, object] | None: ...


class _RecordingAuditWriter:
    def __init__(self) -> None:
        self.events: list[_AuditRow] = []

    def emit(self, event: _AuditRow) -> int:
        self.events.append(event)
        return len(self.events)

    def close(self) -> None:
        return None


@dataclass
class _Cycle:
    service: CodeCloneMCPService
    root: Path
    audit: _RecordingAuditWriter
    intent_id: str
    before_execution_id: str

    def analyze(self) -> str:
        summary = self.service.analyze_repository(
            MCPAnalysisRequest(root=str(self.root), respect_pyproject=False)
        )
        return str(summary["run_id"])

    def write(self, value: int) -> None:
        self.root.joinpath("pkg", "a.py").write_text(
            f"def f(x: int) -> int:\n    return x + {value}\n", "utf-8"
        )

    def release_pin(self) -> None:
        """What the pin ceiling does to the oldest pin, by the same call."""
        self.service._runs.unpin_execution(self.before_execution_id)


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


@pytest.fixture
def cycle(tmp_path: Path) -> Iterator[_Cycle]:
    root = tmp_path / "repo"
    root.joinpath("pkg").mkdir(parents=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("README.md").write_text("stable\n", "utf-8")
    service = CodeCloneMCPService(history_limit=2)
    audit = _RecordingAuditWriter()
    service._audit_writer_override = audit
    state = _Cycle(
        service=service,
        root=root,
        audit=audit,
        intent_id="",
        before_execution_id="",
    )
    state.write(0)
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    state.analyze()
    started = service.start_controlled_change(
        root=str(root),
        scope={"allowed_files": ["pkg/a.py", "README.md"]},
        intent="edit pkg.a",
    )
    assert started["status"] == "active"
    state.intent_id = str(started["intent_id"])
    bound = service._active_intents[state.intent_id].before_execution_id
    assert bound is not None
    state.before_execution_id = bound
    yield state


def _retire(cycle: _Cycle) -> None:
    """Lose the before-run, then let an analysis notice it."""
    cycle.analyze()
    cycle.release_pin()
    assert not cycle.service._runs.holds_execution(cycle.before_execution_id)
    cycle.analyze()


def _expected_typed_answer(intent_id: str) -> dict[str, object]:
    return {
        "intent_id": intent_id,
        "status": "unverified",
        "reason": REASON,
        "next_step": patch_msgs.next_step_hint(REASON),
        "message": intent_msgs.BEFORE_RUN_EVICTED,
    }


# ── the state transition ────────────────────────────────────────────────


def test_an_analysis_retires_the_intent_instead_of_dropping_it(
    cycle: _Cycle,
) -> None:
    _retire(cycle)

    service = cycle.service
    assert cycle.intent_id not in service._active_intents
    assert cycle.intent_id in service._before_run_evicted_intents


def test_retirement_moves_the_registry_row_to_needs_recovery(
    cycle: _Cycle,
) -> None:
    _retire(cycle)

    row = find_workspace_intent(root=cycle.root, intent_id=cycle.intent_id)
    assert row is not None
    assert row.status == "needs_recovery"


def test_an_unreadable_registry_does_not_fail_the_retiring_analysis(
    cycle: _Cycle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import codeclone.surfaces.mcp._session_intent_mixin as intent_mixin
    from codeclone.surfaces.mcp._workspace_intent_store import (
        WorkspaceIntentRegistryUnreadableError,
    )

    def _unreadable(**_kwargs: object) -> bool:
        raise WorkspaceIntentRegistryUnreadableError(
            backend="file",
            storage_path=cycle.root,
            error="PermissionError: denied",
        )

    monkeypatch.setattr(intent_mixin, "update_workspace_intent_status", _unreadable)

    _retire(cycle)

    assert cycle.intent_id in cycle.service._before_run_evicted_intents
    (retired,) = [
        event
        for event in cycle.audit.events
        if event.intent_id == cycle.intent_id and event.status == REASON
    ]
    assert retired.payload is not None
    assert retired.payload["workspace_synced"] is False


def test_retirement_writes_one_audit_event_naming_the_reason(
    cycle: _Cycle,
) -> None:
    _retire(cycle)

    retired = [
        event
        for event in cycle.audit.events
        if event.intent_id == cycle.intent_id and event.status == REASON
    ]
    assert len(retired) == 1
    assert retired[0].event_type == INTENT_EXPIRED_EVENT
    assert retired[0].severity == "warn"
    # A second analysis finds nothing new to retire: no second event.
    cycle.analyze()
    assert (
        len(
            [
                event
                for event in cycle.audit.events
                if event.intent_id == cycle.intent_id and event.status == REASON
            ]
        )
        == 1
    )


# ── every intent-addressed call answers the one reason ─────────────────────


def test_finish_on_a_retired_intent_answers_before_run_evicted(
    cycle: _Cycle,
) -> None:
    _retire(cycle)

    answer = cycle.service.finish_controlled_change(
        intent_id=cycle.intent_id,
        changed_files=["pkg/a.py"],
    )

    assert answer["status"] == "unverified"
    assert answer["reason"] == REASON
    assert answer["intent_cleared"] is False
    assert answer["next_step"] == patch_msgs.next_step_hint(REASON)
    assert answer["message"] == intent_msgs.BEFORE_RUN_EVICTED
    assert answer["verification"] is None
    assert answer["receipt"] is None


def test_finish_before_any_analysis_noticed_the_loss_answers_typed(
    cycle: _Cycle,
) -> None:
    # The pin is gone and the execution with it, and no analysis has run
    # since: the intent is still in the session's active map.
    cycle.analyze()
    cycle.release_pin()
    assert cycle.intent_id in cycle.service._active_intents

    answer = cycle.service.finish_controlled_change(
        intent_id=cycle.intent_id,
        changed_files=["pkg/a.py"],
    )

    assert answer["reason"] == REASON
    assert answer["status"] == "unverified"
    # Noticing the loss is the same transition an analysis makes.
    assert cycle.intent_id in cycle.service._before_run_evicted_intents
    row = find_workspace_intent(root=cycle.root, intent_id=cycle.intent_id)
    assert row is not None
    assert row.status == "needs_recovery"


def test_the_pin_ceiling_reaches_the_typed_answer(cycle: _Cycle) -> None:
    """The production road to the loss: the oldest pin past the ceiling."""
    for _ in range(MAX_PINNED_MCP_RUNS):
        cycle.analyze()
        latest = cycle.service._runs.records()[-1].execution.execution_event_id
        cycle.service._runs.pin_execution(latest)
    assert not cycle.service._runs.holds_execution(cycle.before_execution_id)

    answer = cycle.service.finish_controlled_change(
        intent_id=cycle.intent_id,
        changed_files=["pkg/a.py"],
    )

    assert answer["reason"] == REASON


@pytest.mark.parametrize(
    ("action", "extra"),
    [
        ("get", {}),
        ("check", {"changed_files": ["pkg/a.py"]}),
        ("renew", {}),
    ],
)
def test_manage_change_intent_answers_before_run_evicted(
    cycle: _Cycle,
    action: str,
    extra: dict[str, object],
) -> None:
    _retire(cycle)

    answer = cycle.service.manage_change_intent(
        action=action,
        intent_id=cycle.intent_id,
        **extra,
    )

    assert answer == _expected_typed_answer(cycle.intent_id)


def test_every_action_the_next_step_names_exists() -> None:
    step = patch_msgs.next_step_hint(REASON)
    assert step is not None
    named = set(re.findall(r"action='(\w+)'", step))
    assert named, "the next step names no manage_change_intent action"
    # The dispatcher's own refusal lists what it accepts: no second list here.
    service = CodeCloneMCPService(history_limit=2)
    with pytest.raises(MCPServiceContractError) as refused:
        service.manage_change_intent(action="no-such-action")
    accepted = set(
        str(refused.value).split("Expected one of: ", 1)[1].rstrip(".").split(", ")
    )
    assert {"recover", "clear"} <= named
    assert named <= accepted, sorted(named - accepted)


# ── the next step, walked ─────────────────────────────────────────────────


def test_the_recover_branch_of_the_next_step_reaches_an_accepted_finish(
    cycle: _Cycle,
) -> None:
    _retire(cycle)
    # The tree is unchanged since the intent was declared: analyse it again
    # and rebind the intent to that run, as the next step says.
    run_id = cycle.analyze()

    recovered = cycle.service.manage_change_intent(
        action="recover",
        root=str(cycle.root),
        run_id=run_id,
        intent_id=cycle.intent_id,
    )

    assert recovered["action_taken"] == "recovered", recovered
    assert cycle.intent_id in cycle.service._active_intents
    assert cycle.intent_id not in cycle.service._before_run_evicted_intents
    cycle.root.joinpath("pkg", "a.py").write_text(
        "def f(x: int) -> int:\n    return x * 2\n", "utf-8"
    )
    after = cycle.analyze()
    finished = cycle.service.finish_controlled_change(
        intent_id=cycle.intent_id,
        changed_files=["pkg/a.py"],
        after_run_id=after,
    )
    assert finished["status"] in {"accepted", "accepted_with_external_changes"}, (
        finished
    )
    assert finished["intent_cleared"] is True


def test_the_clear_branch_of_the_next_step_leaves_a_fresh_start(
    cycle: _Cycle,
) -> None:
    _retire(cycle)
    # The tree moved since the declaration: recover must refuse, typed.
    cycle.root.joinpath("pkg", "a.py").write_text(
        "def f(x: int) -> int:\n    return x * 3\n", "utf-8"
    )
    run_id = cycle.analyze()
    refused = cycle.service.manage_change_intent(
        action="recover",
        root=str(cycle.root),
        run_id=run_id,
        intent_id=cycle.intent_id,
    )
    assert refused["action_taken"] == "recovery_rejected"
    assert refused["reason"] != "not_recoverable"

    cleared = cycle.service.manage_change_intent(
        action="clear",
        intent_id=cycle.intent_id,
    )

    assert cleared["cleared_intent_ids"] == [cycle.intent_id]
    assert cleared["workspace_cleared"] is True
    assert cycle.intent_id not in cycle.service._before_run_evicted_intents
    assert find_workspace_intent(root=cycle.root, intent_id=cycle.intent_id) is None
    with pytest.raises(MCPServiceContractError, match="Unknown change intent id"):
        cycle.service.finish_controlled_change(
            intent_id=cycle.intent_id,
            changed_files=["pkg/a.py"],
        )
    # The moved file is this agent's own work in progress, inside the scope it
    # declares again: start's own typed road for that is continue_own_wip.
    restarted = cycle.service.start_controlled_change(
        root=str(cycle.root),
        scope={"allowed_files": ["pkg/a.py"]},
        intent="edit pkg.a again",
        dirty_scope_policy="continue_own_wip",
    )
    assert restarted["status"] == "active", restarted


def test_clear_of_every_intent_includes_the_retired_ones(cycle: _Cycle) -> None:
    _retire(cycle)

    cleared = cycle.service.manage_change_intent(action="clear")

    assert cleared["cleared_intent_ids"] == [cycle.intent_id]
    assert cycle.service._before_run_evicted_intents == {}


def test_shutdown_removes_the_retired_intents_registry_row(cycle: _Cycle) -> None:
    _retire(cycle)

    cycle.service.shutdown_cleanup()

    assert find_workspace_intent(root=cycle.root, intent_id=cycle.intent_id) is None


# ── surfaces that only name an intent ─────────────────────────────────────


def test_implementation_context_names_the_lost_run_not_an_unknown_intent(
    cycle: _Cycle,
) -> None:
    _retire(cycle)

    with pytest.raises(MCPServiceContractError) as raised:
        cycle.service.get_implementation_context(
            root=str(cycle.root),
            intent_id=cycle.intent_id,
            paths=["pkg/a.py"],
        )

    assert "analysis run is no longer available" in str(raised.value)


def test_a_standalone_receipt_names_the_reason(cycle: _Cycle) -> None:
    _retire(cycle)

    with pytest.raises(MCPServiceContractError) as raised:
        cycle.service.create_review_receipt(
            root=str(cycle.root),
            intent_id=cycle.intent_id,
        )

    assert REASON in str(raised.value)


def test_finish_contains_a_run_miss_raised_by_the_receipt(
    cycle: _Cycle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle.root.joinpath("README.md").write_text("changed\n", "utf-8")

    def _receipt_lost_its_run(**_kwargs: object) -> dict[str, object]:
        raise MCPRunNotFoundError("No MCP analysis execution 'x' is available.")

    monkeypatch.setattr(cycle.service, "create_review_receipt", _receipt_lost_its_run)
    answer = cycle.service.finish_controlled_change(
        intent_id=cycle.intent_id,
        changed_files=["README.md"],
    )

    assert answer["status"] in {"accepted", "accepted_with_external_changes"}
    assert "No MCP analysis execution" in str(answer["receipt_error"])
    assert answer["intent_cleared"] is False


# ── what was already typed keeps its bytes ────────────────────────────────


def test_positive_control_a_held_before_run_finishes_accepted(
    cycle: _Cycle,
) -> None:
    cycle.root.joinpath("README.md").write_text("changed\n", "utf-8")

    answer = cycle.service.finish_controlled_change(
        intent_id=cycle.intent_id,
        changed_files=["README.md"],
    )

    assert answer["status"] in {"accepted", "accepted_with_external_changes"}
    assert answer["intent_cleared"] is True


def _queue(cycle: _Cycle) -> None:
    """The two in-memory effects of a downgrade to queued, as it makes them."""
    intent = cycle.service._active_intents[cycle.intent_id]
    cycle.service._active_intents[cycle.intent_id] = replace(
        intent, status=IntentStatus.QUEUED
    )
    cycle.release_pin()


def test_promote_of_a_retired_queued_intent_keeps_its_bytes(cycle: _Cycle) -> None:
    _queue(cycle)
    cycle.analyze()
    cycle.analyze()
    assert cycle.intent_id in cycle.service._before_run_evicted_intents

    answer = cycle.service.manage_change_intent(
        action="promote",
        intent_id=cycle.intent_id,
    )

    assert answer == {
        "intent_id": cycle.intent_id,
        "status": "unverified",
        "reason": REASON,
        "next_step": intent_msgs.PROMOTE_BEFORE_RUN_EVICTED_NEXT,
        "message": intent_msgs.PROMOTE_BEFORE_RUN_EVICTED,
    }
    # A queued intent holds no scope, and its row says so still.
    row = find_workspace_intent(root=cycle.root, intent_id=cycle.intent_id)
    assert row is not None
    assert row.status == "queued"


def test_finish_of_a_retired_queued_intent_keeps_the_queued_answer(
    cycle: _Cycle,
) -> None:
    _queue(cycle)
    held = cycle.service.finish_controlled_change(
        intent_id=cycle.intent_id,
        changed_files=["pkg/a.py"],
    )
    cycle.analyze()
    cycle.analyze()
    assert cycle.intent_id in cycle.service._before_run_evicted_intents

    retired = cycle.service.finish_controlled_change(
        intent_id=cycle.intent_id,
        changed_files=["pkg/a.py"],
    )

    assert held["reason"] == "intent_not_active"
    assert retired == held


def test_atomic_verify_keeps_no_before_run_for_a_retired_intent(
    cycle: _Cycle,
) -> None:
    _retire(cycle)

    retired = cycle.service.check_patch_contract(
        mode="verify",
        intent_id=cycle.intent_id,
        changed_files=["pkg/a.py"],
    )
    never_declared = cycle.service.check_patch_contract(
        mode="verify",
        intent_id="intent-never-declared-001",
        changed_files=["pkg/a.py"],
    )

    assert retired["reason"] == "no_before_run"
    assert retired == never_declared


# ── a superseded intent's pin ──────────────────────────────────────────────


def _pins_on(cycle: _Cycle, execution_event_id: str) -> int:
    return cycle.service._runs._pinned.get(execution_event_id, 0)


def test_superseding_releases_the_superseded_intents_pin(cycle: _Cycle) -> None:
    for _ in range(4):
        replaced = cycle.service.manage_change_intent(
            action="declare",
            root=str(cycle.root),
            scope={"allowed_files": ["pkg/a.py"]},
            intent="declare again on the same run",
        )
        assert replaced["replaced_intents"]

    assert _pins_on(cycle, cycle.before_execution_id) == 1


def test_superseding_a_queued_intent_keeps_the_new_intents_pin(
    cycle: _Cycle,
) -> None:
    _queue(cycle)
    # Keep the execution resolvable while nothing pins it.
    assert cycle.service._runs.holds_execution(cycle.before_execution_id)

    declared = cycle.service.manage_change_intent(
        action="declare",
        root=str(cycle.root),
        scope={"allowed_files": ["pkg/a.py"]},
        intent="replace the queued intent",
    )

    assert declared["edit_allowed"] is True
    assert _pins_on(cycle, cycle.before_execution_id) == 1


def test_superseding_never_lets_the_shared_run_go_between_release_and_pin(
    cycle: _Cycle,
) -> None:
    # Two later runs of other reports fill the unpinned history: the moment
    # the intent's execution is unpinned it is the oldest unpinned one.
    first_run_id = cycle.service._active_intents[cycle.intent_id].run_id
    later_run_ids = set()
    for n in (1, 2):
        cycle.root.joinpath("pkg", f"m{n}.py").write_text(
            f"def g{n}() -> int:\n    return {n}\n", "utf-8"
        )
        later_run_ids.add(cycle.analyze())
    # The probe reaches the mechanism only if the three runs are three reports.
    assert len(later_run_ids) == 2
    assert first_run_id[:8] not in later_run_ids

    declared = cycle.service.manage_change_intent(
        action="declare",
        run_id=first_run_id,
        root=str(cycle.root),
        scope={"allowed_files": ["pkg/a.py"]},
        intent="declare again on the first run",
    )

    assert declared["replaced_intents"]
    assert cycle.service._runs.holds_execution(cycle.before_execution_id)
    assert _pins_on(cycle, cycle.before_execution_id) == 1


def test_a_retired_queued_intent_is_not_recovered_past_its_queue(
    cycle: _Cycle,
) -> None:
    _queue(cycle)
    cycle.analyze()
    run_id = cycle.analyze()
    assert cycle.intent_id in cycle.service._before_run_evicted_intents

    refused = cycle.service.manage_change_intent(
        action="recover",
        root=str(cycle.root),
        run_id=run_id,
        intent_id=cycle.intent_id,
    )

    assert refused["action_taken"] == "recovery_rejected"
    assert refused["reason"] == "not_recoverable"
    assert cycle.intent_id not in cycle.service._active_intents


def test_an_id_handed_out_again_after_clear_session_runs_names_the_new_intent(
    cycle: _Cycle,
) -> None:
    _retire(cycle)
    cycle.service.clear_session_runs()
    # clear_session_runs restarts the intent sequence: the same tree hands
    # out the retired intent's id again.
    cycle.analyze()
    again = cycle.service.start_controlled_change(
        root=str(cycle.root),
        scope={"allowed_files": ["pkg/a.py"]},
        intent="edit pkg.a once more",
    )
    assert again["intent_id"] == cycle.intent_id

    cycle.service.manage_change_intent(action="clear", intent_id=cycle.intent_id)

    with pytest.raises(MCPServiceContractError, match="Unknown change intent id"):
        cycle.service.manage_change_intent(action="get", intent_id=cycle.intent_id)
