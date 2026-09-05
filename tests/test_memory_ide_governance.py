# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import (
    STATEMENT_ORIGIN_AGENT,
    STATEMENT_ORIGIN_HUMAN_AMENDED,
    amend_and_approve_record,
    record_candidate,
    resolve_statement_origin,
    supersede_approved_record,
)
from codeclone.memory.ide_governance import (
    GOVERNANCE_MODE_UNAVAILABLE_NEXT_STEP,
    IDE_GOVERNANCE_PROTOCOL_VERSION,
    IdeGovernanceSessionState,
    commit_governance,
    compute_governance_proof,
    compute_statement_digest,
    prepare_governance,
    register_ide_governance,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.surfaces.mcp.service import CodeCloneMCPService


def _governance_key_hex() -> str:
    return secrets.token_hex(32)


def test_agent_approve_action_rejected_by_mcp(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    service = CodeCloneMCPService()
    payload = service.manage_engineering_memory(
        root=str(root),
        action="approve",
        record_id="mem-1",
    )
    assert payload["status"] == "rejected"
    assert payload["reason"] == "governance_mode_unavailable"
    next_step = payload["next_step"]
    assert isinstance(next_step, str)
    assert "codeclone memory approve" not in next_step.lower()
    assert GOVERNANCE_MODE_UNAVAILABLE_NEXT_STEP in next_step


def test_ide_governance_prepare_and_commit_approve(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    key_hex = _governance_key_hex()
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="architecture_decision",
            statement="Use IDE governance for human approval.",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        registered = register_ide_governance(
            state,
            ide_governance_key=key_hex,
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )
        assert registered["status"] == "ok"
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        assert prepared["status"] == "ok"
        ticket_id = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(key_hex),
            ticket_id=ticket_id,
            record_id=draft.id,
            decision="approve",
            confirmation_nonce=nonce,
            project_id=project.id,
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        committed = commit_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
            governance_ticket=ticket_id,
            confirmation_nonce=nonce,
            proof=proof,
            actor="vscode-test",
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        assert committed["status"] == "ok"
        assert committed["record_status"] == "active"
        updated = store.find_record(draft.id)
        assert updated is not None
        assert updated.status == "active"
    finally:
        store.close()


def test_ide_governance_rejects_without_channel(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=False)
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="Draft only.",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        payload = prepare_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        assert payload["status"] == "rejected"
        assert payload["reason"] == "governance_mode_unavailable"
    finally:
        store.close()


def test_ide_governance_commit_rejects_bad_proof(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    key_hex = _governance_key_hex()
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="Needs valid proof.",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        register_ide_governance(
            state,
            ide_governance_key=key_hex,
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        with pytest.raises(MemoryContractError, match="Invalid IDE governance proof"):
            commit_governance(
                state,
                store,
                project_id=project.id,
                root_path=str(root),
                record_id=draft.id,
                decision="approve",
                governance_ticket=str(prepared["governance_ticket"]),
                confirmation_nonce=str(prepared["confirmation_nonce"]),
                proof="0" * 64,
                actor="vscode-test",
                protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
            )
    finally:
        store.close()


def test_ide_governance_prepare_and_commit_reject(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    state = IdeGovernanceSessionState(channel_enabled=True)
    key_hex = _governance_key_hex()
    try:
        store.initialize(project)
        draft = record_candidate(
            store,
            project=project,
            record_type="change_rationale",
            statement="Reject after review.",
            subject_path="pkg/mod.py",
            max_candidates=100,
        )
        register_ide_governance(
            state,
            ide_governance_key=key_hex,
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="reject",
        )
        proof = compute_governance_proof(
            bytes.fromhex(key_hex),
            ticket_id=str(prepared["governance_ticket"]),
            record_id=draft.id,
            decision="reject",
            confirmation_nonce=str(prepared["confirmation_nonce"]),
            project_id=project.id,
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        committed = commit_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(root),
            record_id=draft.id,
            decision="reject",
            governance_ticket=str(prepared["governance_ticket"]),
            confirmation_nonce=str(prepared["confirmation_nonce"]),
            proof=proof,
            actor="vscode-test",
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        assert committed["status"] == "ok"
        updated = store.find_record(draft.id)
        assert updated is not None
        assert updated.status == "rejected"
    finally:
        store.close()


def test_ide_governance_validate_reject_is_draft_only() -> None:
    # Audit M7: IDE _validate_record_for_decision now mirrors governance.py —
    # reject is draft-only (stale is discarded via vacuum, never human-rejected),
    # approve accepts {draft, stale}, archive accepts active. Closes the gap where
    # a VS Code reject on a stale record passed IDE validation, then raised a
    # MemoryContractError inside reject_record.
    from dataclasses import replace

    from codeclone.memory.ide_governance import _validate_record_for_decision
    from tests.memory_fixtures import make_module_record

    base = make_module_record("proj-m7", "pkg.mod")
    stale = replace(base, status="stale")
    with pytest.raises(
        MemoryContractError, match="Cannot reject record in status 'stale'"
    ):
        _validate_record_for_decision(stale, "reject")
    # approve on stale (re-verify) and reject on draft both remain valid.
    _validate_record_for_decision(stale, "approve")
    _validate_record_for_decision(replace(base, status="draft"), "reject")


# ==========================================================================
# The draft-amendment bridge: atomic amend+approve under a full CAS.
#
# Every pin below answers one question -- could the human's approval have been
# bound to text the human never saw? The CAS axes are pinned one per test so a
# mutation of any single axis reds a different test.
# ==========================================================================


_CLIENT = "CodeClone VS Code"


def _reader_row(db_path: Path, record_id: str) -> tuple[str, int]:
    """Read committed state on a SEPARATE connection.

    Probe validity: an in-process read would see the writer's own
    uncommitted transaction and could never distinguish "committed" from
    "pending", so it could not see the effect this test claims to measure.
    """
    conn = sqlite3.connect(db_path)
    try:
        status = conn.execute(
            "SELECT status FROM memory_records WHERE id=?", (record_id,)
        ).fetchone()
        revisions = conn.execute(
            "SELECT COUNT(*) FROM memory_revisions WHERE memory_id=?", (record_id,)
        ).fetchone()
        return str(status[0]), int(revisions[0])
    finally:
        conn.close()


class _Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.db_path = tmp_path / "memory.sqlite3"
        self.project = resolve_project_identity(self.root)
        self.store = SqliteEngineeringMemoryStore(self.db_path)
        self.store.initialize(self.project)
        self.state = IdeGovernanceSessionState(channel_enabled=True)
        self.key_hex = secrets.token_hex(32)
        register_ide_governance(
            self.state,
            ide_governance_key=self.key_hex,
            client_name=_CLIENT,
            client_version="0.3.0",
        )

    # Returns whatever record_candidate returns. Deliberately not annotated
    # with the model type: naming it would import the model store into a test
    # that only exercises the governance API -- a ring crossing the
    # architecture ratchet is right to flag.
    def draft(self, statement: str, *, path: str = "pkg/mod.py") -> Any:
        return record_candidate(
            self.store,
            project=self.project,
            record_type="change_rationale",
            statement=statement,
            subject_path=path,
            max_candidates=100,
        )

    def prepare(self, record_id: str, decision: str) -> dict[str, object]:
        return prepare_governance(
            self.state,
            self.store,
            project_id=self.project.id,
            root_path=str(self.root),
            record_id=record_id,
            decision=decision,
        )

    def commit(
        self,
        record_id: str,
        decision: str,
        prepared: dict[str, object],
        *,
        statement: str | None = None,
        actor: str = "maintainer",
    ) -> dict[str, object]:
        ticket_id = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(self.key_hex),
            ticket_id=ticket_id,
            record_id=record_id,
            decision=decision,
            confirmation_nonce=nonce,
            project_id=self.project.id,
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        return commit_governance(
            self.state,
            self.store,
            project_id=self.project.id,
            root_path=str(self.root),
            record_id=record_id,
            decision=decision,
            governance_ticket=ticket_id,
            confirmation_nonce=nonce,
            proof=proof,
            actor=actor,
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
            statement=statement,
        )

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[_Harness]:
    made = _Harness(tmp_path)
    try:
        yield made
    finally:
        made.close()


# --------------------------------------------------------------------------
# CAS axis 1: the statement moved between show and commit.
# --------------------------------------------------------------------------


def test_changed_statement_is_refused_as_stale_amendment(harness: _Harness) -> None:
    """Arm 1 re-typed: the ticket matched; it was the RECORD that moved."""
    draft = harness.draft("Original wording.")
    prepared = harness.prepare(draft.id, "approve")
    harness.store.update_record_statement(
        draft.id, statement="Someone else rewrote this.", commit=True
    )
    with pytest.raises(MemoryContractError) as excinfo:
        harness.commit(draft.id, "approve", prepared)
    message = str(excinfo.value)
    assert message.startswith("governance_stale_amendment:")
    assert "next_step:" in message
    assert 'help(topic="engineering_memory")' in message
    # The true cause is named; the ticket is not blamed for it.
    assert "does not match the commit request" not in message
    assert _reader_row(harness.db_path, draft.id)[0] == "draft"


def test_true_ticket_mismatch_still_names_the_ticket(harness: _Harness) -> None:
    """The other side of the split: a request that really contradicts its ticket."""
    first = harness.draft("Ticket belongs to this one.")
    second = harness.draft("A different draft entirely.")
    prepared = harness.prepare(first.id, "approve")
    with pytest.raises(MemoryContractError) as excinfo:
        harness.commit(second.id, "approve", prepared)
    message = str(excinfo.value)
    assert message.startswith("governance_ticket_mismatch:")
    assert not message.startswith("governance_stale_amendment:")


# --------------------------------------------------------------------------
# CAS axis 2: the record's lifecycle status moved (arm 2 — the measured hole).
# --------------------------------------------------------------------------


def test_stale_record_shown_as_draft_is_refused_at_commit(harness: _Harness) -> None:
    """Arm 2. Statement bytes never changed; the record still moved.

    ``mark_stale`` writes no revision row, so the revision axis alone cannot
    see this. The status axis is what makes the CAS total.
    """
    draft = harness.draft("Wording nobody touched.")
    prepared = harness.prepare(draft.id, "approve")
    assert str(prepared["statement_digest"]) == compute_statement_digest(
        draft.statement
    )
    harness.store.mark_stale(draft.id, "superseded by a later run")
    with pytest.raises(MemoryContractError) as excinfo:
        harness.commit(draft.id, "approve", prepared)
    assert str(excinfo.value).startswith("governance_stale_amendment:")
    assert _reader_row(harness.db_path, draft.id)[0] == "stale"


def test_stale_move_leaves_the_revision_axis_blind(harness: _Harness) -> None:
    """Probe validity for the test above: prove the OTHER axis could not see it.

    If mark_stale bumped the revision, the arm-2 pin would pass for the wrong
    reason and mutating the status axis away would not red it.
    """
    draft = harness.draft("Revision axis witness.")
    before = harness.store.next_revision_number(draft.id)
    harness.store.mark_stale(draft.id, "moved without a revision")
    assert harness.store.next_revision_number(draft.id) == before


# --------------------------------------------------------------------------
# CAS axis 3: the revision moved.
# --------------------------------------------------------------------------


def test_amend_refused_when_revision_moved(harness: _Harness) -> None:
    draft = harness.draft("Text that survives the concurrent revision.")
    prepared = harness.prepare(draft.id, "amend_and_approve")
    shown_revision = int(prepared["current_revision"])  # type: ignore[call-overload]
    with pytest.raises(MemoryContractError) as excinfo:
        amend_and_approve_record(
            harness.store,
            record_id=draft.id,
            submitted_statement="Human wording.",
            expected_revision=shown_revision + 1,
            shown_statement_digest=str(prepared["statement_digest"]),
            shown_status="draft",
            approved_by="maintainer",
        )
    assert str(excinfo.value).startswith("governance_stale_amendment:")
    assert _reader_row(harness.db_path, draft.id) == ("draft", 0)


def test_amend_refused_on_hand_set_shown_digest(harness: _Harness) -> None:
    """Guard coverage, not just mechanism coverage."""
    draft = harness.draft("Untouched text.")
    prepared = harness.prepare(draft.id, "amend_and_approve")
    with pytest.raises(MemoryContractError) as excinfo:
        amend_and_approve_record(
            harness.store,
            record_id=draft.id,
            submitted_statement="Human wording.",
            expected_revision=int(prepared["current_revision"]),  # type: ignore[call-overload]
            shown_statement_digest="0" * 32,
            shown_status="draft",
            approved_by="maintainer",
        )
    assert str(excinfo.value).startswith("governance_stale_amendment:")
    assert _reader_row(harness.db_path, draft.id) == ("draft", 0)


def test_amend_refused_on_real_concurrent_rewrite(harness: _Harness) -> None:
    """A real second writer, not a hand-set field."""
    draft = harness.draft("First author wording.")
    prepared = harness.prepare(draft.id, "amend_and_approve")
    other = SqliteEngineeringMemoryStore(harness.db_path)
    try:
        other.update_record_statement(
            draft.id, statement="Second writer got here first.", commit=True
        )
    finally:
        other.close()
    with pytest.raises(MemoryContractError) as excinfo:
        amend_and_approve_record(
            harness.store,
            record_id=draft.id,
            submitted_statement="Human wording.",
            expected_revision=int(prepared["current_revision"]),  # type: ignore[call-overload]
            shown_statement_digest=str(prepared["statement_digest"]),
            shown_status="draft",
            approved_by="maintainer",
        )
    assert str(excinfo.value).startswith("governance_stale_amendment:")
    assert _reader_row(harness.db_path, draft.id)[0] == "draft"


# --------------------------------------------------------------------------
# Atomicity.
# --------------------------------------------------------------------------


def test_plain_approve_is_atomic_across_an_injected_failure(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The measured defect: a crash after the status write left ('active', 0)."""
    draft = harness.draft("Atomicity of the plain approve path.")
    prepared = harness.prepare(draft.id, "approve")
    assert _reader_row(harness.db_path, draft.id) == ("draft", 0)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected failure after the status write")

    monkeypatch.setattr(harness.store, "write_revision", _boom)
    with pytest.raises(RuntimeError, match="injected failure"):
        harness.commit(draft.id, "approve", prepared)
    assert _reader_row(harness.db_path, draft.id) == ("draft", 0)


def test_amend_and_approve_is_atomic_across_an_injected_failure(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = harness.draft("Atomicity of the amend path.")
    prepared = harness.prepare(draft.id, "amend_and_approve")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected failure mid-transaction")

    monkeypatch.setattr(harness.store, "write_revision", _boom)
    with pytest.raises(RuntimeError, match="injected failure"):
        amend_and_approve_record(
            harness.store,
            record_id=draft.id,
            submitted_statement="Human wording that must not land.",
            expected_revision=int(prepared["current_revision"]),  # type: ignore[call-overload]
            shown_statement_digest=str(prepared["statement_digest"]),
            shown_status="draft",
            approved_by="maintainer",
        )
    assert _reader_row(harness.db_path, draft.id) == ("draft", 0)
    landed = harness.store.find_record(draft.id)
    assert landed is not None
    assert landed.statement == "Atomicity of the amend path."


# --------------------------------------------------------------------------
# Happy path, provenance, immutability.
# --------------------------------------------------------------------------


def test_amend_and_approve_commits_text_and_approval_together(
    harness: _Harness,
) -> None:
    draft = harness.draft("## Agent wording\nThe agent's first draft.")
    prepared = harness.prepare(draft.id, "amend_and_approve")
    assert prepared["statement_origin"] == STATEMENT_ORIGIN_AGENT
    amended = "## Human wording\nThe maintainer read it and rewrote it."
    result = harness.commit(draft.id, "amend_and_approve", prepared, statement=amended)
    assert result["status"] == "ok"
    assert result["record_status"] == "active"
    assert result["statement_origin"] == STATEMENT_ORIGIN_HUMAN_AMENDED
    updated = harness.store.find_record(draft.id)
    assert updated is not None
    assert updated.statement == amended
    assert updated.status == "active"
    status, revisions = _reader_row(harness.db_path, draft.id)
    assert (status, revisions) == ("active", 1)
    proof = result["proof"]
    assert isinstance(proof, dict)
    assert proof["operation"] == "amend_and_approve"
    assert proof["shown_statement_digest"] == str(prepared["statement_digest"])
    assert proof["submitted_statement_digest"] == compute_statement_digest(amended)
    assert proof["expected_revision_matched"] is True
    assert proof["revision_created"] == 1


def test_created_by_is_not_rewritten_by_an_amendment(harness: _Harness) -> None:
    """``human_amended`` is not an author. created_by is a historical fact."""
    draft = harness.draft("Wording authored by the agent.")
    assert draft.created_by == "agent"
    prepared = harness.prepare(draft.id, "amend_and_approve")
    harness.commit(
        draft.id,
        "amend_and_approve",
        prepared,
        statement="Wording the maintainer rewrote.",
        actor="den",
    )
    updated = harness.store.find_record(draft.id)
    assert updated is not None
    assert updated.created_by == "agent"
    assert updated.approved_by == "den"
    assert resolve_statement_origin(updated.payload) == STATEMENT_ORIGIN_HUMAN_AMENDED


def test_statement_origin_stays_agent_on_an_unamended_approve(
    harness: _Harness,
) -> None:
    draft = harness.draft("Approved exactly as the agent wrote it.")
    prepared = harness.prepare(draft.id, "approve")
    harness.commit(draft.id, "approve", prepared)
    updated = harness.store.find_record(draft.id)
    assert updated is not None
    assert resolve_statement_origin(updated.payload) == STATEMENT_ORIGIN_AGENT


def test_amend_on_an_approved_record_is_refused(harness: _Harness) -> None:
    """approved is immutable — the correction is a successor, not an edit."""
    draft = harness.draft("Published engineering statement.")
    prepared = harness.prepare(draft.id, "approve")
    harness.commit(draft.id, "approve", prepared)
    with pytest.raises(MemoryContractError) as excinfo:
        harness.prepare(draft.id, "amend_and_approve")
    message = str(excinfo.value)
    assert message.startswith("governance_record_immutable:")
    assert "next_step:" in message
    assert 'help(topic="engineering_memory")' in message
    unchanged = harness.store.find_record(draft.id)
    assert unchanged is not None
    assert unchanged.statement == "Published engineering statement."


def test_supersede_creates_a_linked_successor_candidate(harness: _Harness) -> None:
    draft = harness.draft("The approved statement that needs a correction.")
    prepared = harness.prepare(draft.id, "approve")
    harness.commit(draft.id, "approve", prepared)
    successor = supersede_approved_record(
        harness.store,
        project=harness.project,
        record_id=draft.id,
        statement="The corrected statement.",
        actor="den",
        max_candidates=100,
    )
    assert successor.id != draft.id
    assert successor.status == "draft"
    assert resolve_statement_origin(successor.payload) == STATEMENT_ORIGIN_HUMAN_AMENDED
    links = harness.store.list_links_for_records(
        project_id=harness.project.id,
        record_ids=[successor.id],
        relations=["supersedes"],
    )
    assert [(link.relation, link.to_memory_id) for link in links] == [
        ("supersedes", draft.id)
    ]
    predecessor = harness.store.find_record(draft.id)
    assert predecessor is not None
    assert predecessor.statement == "The approved statement that needs a correction."
    assert predecessor.status == "active"


# --------------------------------------------------------------------------
# Validation parity: same rules, human-executable next_step.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ("Wording with <b>raw html</b>.", "memory_md_html"),
        ("Wording with <code>a code tag</code>.", "memory_md_html"),
        ("Wording with ![shot](https://example.test/x.png).", "memory_md_image"),
        ("Wording with [a link](https://example.test).", "memory_md_link"),
    ],
)
def test_human_submitted_statement_obeys_the_agent_rules(
    harness: _Harness, payload: str, code: str
) -> None:
    draft = harness.draft("Clean agent wording.")
    prepared = harness.prepare(draft.id, "amend_and_approve")
    with pytest.raises(MemoryContractError) as excinfo:
        harness.commit(draft.id, "amend_and_approve", prepared, statement=payload)
    message = str(excinfo.value)
    assert message.startswith(f"{code}:")
    # The remedy must be executable by a human in the approval view.
    assert "action=record_candidate" not in message
    assert "Memory view" in message
    assert 'help(topic="engineering_memory")' in message
    assert _reader_row(harness.db_path, draft.id) == ("draft", 0)


def test_agent_channel_cannot_approve_or_amend(harness: _Harness) -> None:
    """The gate is the launch flag (a process boundary), not a name check.

    Probe validity: the agent state is exercised against a REAL initialised
    store and a real draft, so the call reaches the channel gate. Pointing it
    at an empty directory would fail earlier on "database not found" and
    prove nothing about who may approve.
    """
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

    draft = harness.draft("A draft an agent would love to self-approve.")
    # What a server launched WITHOUT --ide-governance-channel carries.
    agent_state = IdeGovernanceSessionState()
    assert agent_state.channel_enabled is False

    prepared = prepare_governance(
        agent_state,
        harness.store,
        project_id=harness.project.id,
        root_path=str(harness.root),
        record_id=draft.id,
        decision="amend_and_approve",
    )
    assert prepared["status"] == "rejected"
    assert prepared["reason"] == "governance_mode_unavailable"

    committed = commit_governance(
        agent_state,
        harness.store,
        project_id=harness.project.id,
        root_path=str(harness.root),
        record_id=draft.id,
        decision="amend_and_approve",
        governance_ticket="t",
        confirmation_nonce="n",
        proof="p",
        actor="agent",
        protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        statement="Text an agent tried to publish by itself.",
    )
    assert committed["status"] == "rejected"
    assert committed["reason"] == "governance_mode_unavailable"

    # And the record never moved.
    assert _reader_row(harness.db_path, draft.id) == ("draft", 0)

    # The MCP surface refuses the bare decision verbs outright.
    service = CodeCloneMCPService()
    payload = service.manage_engineering_memory(
        root=str(harness.root), action="approve", record_id=draft.id
    )
    assert payload["status"] == "rejected"
    assert payload["reason"] == "governance_mode_unavailable"
