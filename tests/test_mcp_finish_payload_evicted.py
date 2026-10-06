# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``finish_controlled_change`` over a before-run held without its payload.

The maintainer's acceptance (2026-09-08): a before-run evicted from memory
whose run the store holds valid -- finish is still reachable; a run neither
memory nor the store holds -- a typed recovery outcome, never an intent that
silently vanishes.  Driven end to end on temporary repositories with their
own stores (the rollout and the serving switch set inside the test, never a
production store):

* the payload dropped with the registry's lever, and by real pressure (an
  analysis of another checkout in the same session): the same verdict, the
  same verification, the same receipt verdict as with the payload;
* claims text: answered "not validated: payload evicted", the verdict kept;
* an unpublished before-run: its payload is never dropped, finish as today;
* a before-run the store cannot answer either: ``before_run_evicted`` with
  the recover-or-clear road, the intent kept and retired, its registry row
  moved, and the clear branch leaving a fresh start.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.api.run_residence import ResidentRun
from codeclone.surfaces.mcp._run_residence import resident_identity
from codeclone.surfaces.mcp._session_shared import MCPRunRecord
from codeclone.surfaces.mcp._workspace_intents import find_workspace_intent
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest


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


class _RecordingAuditWriter:
    def __init__(self) -> None:
        self.statuses: list[str] = []

    def emit(self, event: object) -> int:
        self.statuses.append(str(getattr(event, "status", "")))
        return len(self.statuses)

    def close(self) -> None:
        return None


def _repo(base: Path, name: str) -> Path:
    root = base / name
    root.joinpath("pkg").mkdir(parents=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("pkg", "m.py").write_text(
        "def f(x: int) -> int:\n    return x + 1\n", "utf-8"
    )
    root.joinpath(".gitignore").write_text(".cache/\n.codeclone/\n", "utf-8")
    for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "init")):
        _git(root, *args)
    return root


@dataclass
class _Cycle:
    root: Path
    service: CodeCloneMCPService
    intent_id: str
    before: MCPRunRecord
    after_run_id: str = ""

    def analyze(self, root: Path | None = None) -> MCPRunRecord:
        self.service.analyze_repository(
            MCPAnalysisRequest(root=str(root or self.root), respect_pyproject=False)
        )
        return self.service._runs.records()[-1]

    def edit_and_analyze(self) -> None:
        self.root.joinpath("pkg", "m.py").write_text(
            "def f(x: int) -> int:\n    return x + 2\n\n\n"
            "def g(y: int) -> int:\n    return y * 2\n",
            "utf-8",
        )
        self.after_run_id = self.analyze().run_id
        # The population holds a pair of two runs, not the analyzer-invariant
        # same-id case: the receipt compares the before-run to the after-run.
        assert self.after_run_id != self.before.run_id

    def drop_before(self) -> None:
        assert self.service._runs.drop_payload(resident_identity(self.before))

    def held_before(self) -> object:
        return self.service._runs.held_execution(
            self.before.execution.execution_event_id
        )

    def finish(self, **extra: object) -> dict[str, object]:
        return self.service.finish_controlled_change(
            intent_id=self.intent_id,
            after_run_id=self.after_run_id,
            changed_files=["pkg/m.py"],
            **extra,
        )


@pytest.fixture
def store_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(tmp_path / "runs.sqlite3"))
    monkeypatch.setenv("CODECLONE_SERVE_FROM", "run_store")
    return tmp_path / "runs.sqlite3"


def _cycle(base: Path, name: str = "repo", path: str = "pkg/m.py") -> _Cycle:
    root = _repo(base, name)
    service = CodeCloneMCPService(history_limit=2)
    service.analyze_repository(
        MCPAnalysisRequest(root=str(root), respect_pyproject=False)
    )
    before = service._runs.records()[-1]
    started = service.start_controlled_change(
        root=str(root), scope={"allowed_files": [path]}, intent=f"edit {path}"
    )
    assert started["status"] == "active", started
    return _Cycle(root, service, str(started["intent_id"]), before)


#: What a finish decides, compared across the drop: every field but the
#: emission facts and the paths of the checkout it ran in.
def _decided(answer: Mapping[str, object]) -> dict[str, object]:
    verification = dict(answer["verification"])  # type: ignore[call-overload]
    for emitted in ("serving", "_audit_sequence"):
        verification.pop(emitted, None)
    receipt = answer["receipt"]
    assert isinstance(receipt, Mapping), answer
    return {
        "status": answer["status"],
        "reason": answer["reason"],
        "verification": verification,
        "scope_status": dict(answer["scope_check"])["status"],  # type: ignore[call-overload]
        "receipt_verdict": receipt["verdict"],
        "intent_cleared": answer["intent_cleared"],
        "summary": answer["summary"],
    }


@pytest.fixture
def control(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    base = tmp_path_factory.mktemp("control")
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(base / "runs.sqlite3"))
    monkeypatch.setenv("CODECLONE_SERVE_FROM", "run_store")
    cycle = _cycle(base)
    cycle.edit_and_analyze()
    return cycle.finish()


def test_the_control_finish_with_the_payload_is_accepted(
    control: dict[str, object],
) -> None:
    assert control["status"] == "accepted"
    assert control["intent_cleared"] is True


def test_a_before_run_without_its_payload_reaches_the_same_verdict(
    control: dict[str, object], store_on: Path, tmp_path: Path
) -> None:
    cycle = _cycle(tmp_path)
    cycle.edit_and_analyze()
    cycle.drop_before()
    # No memory answer exists to verify the before-run by: only its store copy.
    assert isinstance(cycle.held_before(), ResidentRun)

    answer = cycle.finish()

    assert _decided(answer) == _decided(control)
    # Not asked to validate claims: none, as with the payload.
    assert answer["claims"] is None


def test_real_pressure_drops_the_before_run_and_finish_is_still_reached(
    control: dict[str, object], store_on: Path, tmp_path: Path
) -> None:
    cycle = _cycle(tmp_path)
    cycle.edit_and_analyze()
    # Another checkout analysed in the same session: the history limit (two
    # payloads) makes room by dropping the oldest payload the rule lets go --
    # the leased before-run.
    cycle.analyze(_repo(tmp_path, "other"))
    assert isinstance(cycle.held_before(), ResidentRun)

    answer = cycle.finish()

    assert _decided(answer) == _decided(control)


def test_claims_over_a_before_run_without_payload_are_not_validated(
    control: dict[str, object], store_on: Path, tmp_path: Path
) -> None:
    cycle = _cycle(tmp_path)
    cycle.edit_and_analyze()
    cycle.drop_before()

    answer = cycle.finish(claims_text="No new findings in pkg/m.py.")

    assert answer["status"] == "accepted"
    assert answer["intent_cleared"] is True
    claims = answer["claims"]
    assert isinstance(claims, Mapping)
    assert claims["status"] == "not_validated"
    assert claims["reason"] == "payload_evicted"
    assert claims["valid"] is None
    assert dict(answer["summary"])["claims"] == "not_validated"  # type: ignore[call-overload]


def test_an_unpublished_before_run_keeps_its_payload_and_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "0")
    monkeypatch.setenv("CODECLONE_SERVE_FROM", "run_store")
    cycle = _cycle(tmp_path)
    cycle.edit_and_analyze()
    cycle.analyze(_repo(tmp_path, "other"))

    # Nothing can stand in for it: held whole, as before the drop rule.
    assert cycle.held_before() is cycle.before
    answer = cycle.finish()

    assert answer["status"] == "accepted"
    assert answer["intent_cleared"] is True


def test_a_before_run_neither_memory_nor_the_store_holds_is_typed(
    store_on: Path, tmp_path: Path
) -> None:
    cycle = _cycle(tmp_path)
    cycle.edit_and_analyze()
    cycle.drop_before()
    store_on.unlink()
    audit = _RecordingAuditWriter()
    cycle.service._audit_writer_override = audit

    answer = cycle.finish()

    assert (answer["status"], answer["reason"], answer["intent_cleared"]) == (
        "unverified",
        "before_run_evicted",
        False,
    )
    assert "recover" in str(answer["next_step"])
    # Kept, retired, announced -- never silently gone.
    retired = cycle.service._before_run_evicted_intents
    workspace_row = find_workspace_intent(root=cycle.root, intent_id=cycle.intent_id)
    assert cycle.intent_id in retired
    assert getattr(workspace_row, "status", None) == "needs_recovery"
    assert audit.statuses.count("before_run_evicted") == 1
    # Its pin went with it: the identity nothing answers from ages out.
    assert cycle.service._runs.pin_count(cycle.before.execution.execution_event_id) == 0

    cleared = cycle.service.manage_change_intent(
        action="clear", intent_id=cycle.intent_id
    )
    assert cleared.get("reason") != "payload_evicted", cleared
    restarted = cycle.service.start_controlled_change(
        root=str(cycle.root), scope={"allowed_files": ["README.md"]}, intent="again"
    )
    assert restarted["status"] == "active", restarted


def test_a_docs_only_finish_over_a_before_run_without_payload_reports_its_receipt(
    store_on: Path, tmp_path: Path
) -> None:
    """No after-run: the receipt is the before-run's own, and its findings are
    the payload's.  The verdict stands; the receipt is reported in-band as
    not created, typed, and the intent stays until a whole run answers."""
    cycle = _cycle(tmp_path, path="README.md")
    cycle.root.joinpath("README.md").write_text("changed\n", "utf-8")
    cycle.drop_before()

    answer = cycle.service.finish_controlled_change(
        intent_id=cycle.intent_id, changed_files=["README.md"]
    )

    assert answer["status"] == "accepted", answer
    assert "no longer holds the run's analysis" in str(answer.get("receipt_error")), {
        key: answer.get(key) for key in ("status", "reason", "receipt", "summary")
    }
    assert answer["intent_cleared"] is False
