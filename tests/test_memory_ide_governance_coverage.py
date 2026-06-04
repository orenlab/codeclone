# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import time
from pathlib import Path

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import approve_record, record_candidate
from codeclone.memory.ide_governance import (
    IDE_GOVERNANCE_ALLOWED_CLIENTS,
    IDE_GOVERNANCE_MAX_COMMIT_ATTEMPTS,
    IDE_GOVERNANCE_PROTOCOL_VERSION,
    IdeGovernanceSessionState,
    commit_governance,
    compute_governance_proof,
    prepare_governance,
    register_ide_governance,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore

_VALID_KEY_HEX = "00" * 32  # 32 bytes (64 hex chars)


def _make_store_project_and_state(
    *,
    tmp_path: Path,
    channel_enabled: bool,
) -> tuple[Path, object, SqliteEngineeringMemoryStore, IdeGovernanceSessionState]:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    store.initialize(project)
    state = IdeGovernanceSessionState(channel_enabled=channel_enabled)
    return root, project, store, state


def _register_default_ide_governance(
    *,
    state: IdeGovernanceSessionState,
    root: Path,
    store: SqliteEngineeringMemoryStore,
    key_hex: str,
    client_version: str | None,
) -> None:
    # Helper is intentionally narrow: it registers an IDE governance key for
    # the same repository root used when the store was initialized.
    allowed_client = next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS))
    register_ide_governance(
        state,
        ide_governance_key=key_hex,
        client_name=allowed_client,
        client_version=client_version,
    )


def _prepare_ticket_for_record(
    *,
    state: IdeGovernanceSessionState,
    store: SqliteEngineeringMemoryStore,
    project: object,
    root: Path,
    record_id: str,
    decision: str,
) -> dict[str, object]:
    return prepare_governance(
        state,
        store,
        project_id=project.id,  # type: ignore[attr-defined]
        root_path=str(root),
        record_id=record_id,
        decision=decision,
    )


def test_register_ide_governance_invalid_hex_characters_triggers_cause() -> None:
    # fromhex() ValueError should be chained into MemoryContractError.
    with pytest.raises(MemoryContractError, match="valid hexadecimal"):
        state = IdeGovernanceSessionState(channel_enabled=True)
        register_ide_governance(
            state,
            ide_governance_key="0xzz",
            client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
            client_version="0.3.0",
        )


def test_register_ide_governance_rejects_hex_key_too_short(tmp_path: Path) -> None:
    _, _project_unused, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        with pytest.raises(
            MemoryContractError,
            match="must be at least 32 bytes",
        ):
            register_ide_governance(
                state,
                ide_governance_key=("00" * 31),
                client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
                client_version="0.3.0",
            )
    finally:
        store.close()


def test_register_ide_governance_rejected_when_channel_disabled(tmp_path: Path) -> None:
    _, _, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=False,
    )
    try:
        payload = register_ide_governance(
            state,
            ide_governance_key=_VALID_KEY_HEX,
            client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
            client_version="0.3.0",
        )
        assert payload["status"] == "rejected"
        assert payload["action"] == "register_ide_governance"
    finally:
        store.close()


def test_prepare_governance_returns_not_found_for_missing_record(
    tmp_path: Path,
) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        _register_default_ide_governance(
            state=state,
            root=root,
            store=store,
            key_hex=_VALID_KEY_HEX,
            client_version="0.3.0",
        )
        payload = prepare_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id="mem-missing",
            decision="approve",
        )
        assert payload["status"] == "not_found"
        assert payload["record_id"] == "mem-missing"
    finally:
        store.close()


def test_prepare_governance_rejects_invalid_decision(tmp_path: Path) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        _register_default_ide_governance(
            state=state,
            root=root,
            store=store,
            key_hex=_VALID_KEY_HEX,
            client_version="0.3.0",
        )
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="bad decision",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        with pytest.raises(MemoryContractError, match="Unknown governance decision"):
            prepare_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(root),
                record_id=draft.id,
                decision="maybe",
            )
    finally:
        store.close()


def test_prepare_governance_raises_when_record_status_invalid_for_approve(
    tmp_path: Path,
) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        _register_default_ide_governance(
            state=state,
            root=root,
            store=store,
            key_hex=_VALID_KEY_HEX,
            client_version="0.3.0",
        )
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="invalid status for approve",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        approve_record(store, record_id=draft.id, approved_by="maintainer")
        with pytest.raises(
            MemoryContractError, match="Cannot approve record in status"
        ):
            prepare_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(root),
                record_id=draft.id,
                decision="approve",
            )
    finally:
        store.close()


def test_prepare_governance_raises_when_record_status_invalid_for_archive(
    tmp_path: Path,
) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        _register_default_ide_governance(
            state=state,
            root=root,
            store=store,
            key_hex=_VALID_KEY_HEX,
            client_version="0.3.0",
        )
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="invalid status for archive",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        with pytest.raises(
            MemoryContractError, match="Cannot archive record in status"
        ):
            prepare_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(root),
                record_id=draft.id,
                decision="archive",
            )
    finally:
        store.close()


def test_prepare_governance_rejected_for_disallowed_client_name(tmp_path: Path) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        # Force a non-allowed client_name after key registration.
        register_ide_governance(
            state,
            ide_governance_key=_VALID_KEY_HEX,
            client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
            client_version="0.3.0",
        )
        state.client_name = "NotAllowed IDE"
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="client mismatch",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        payload = prepare_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        assert payload["status"] == "rejected"
        assert payload["action"] == "prepare_governance"
    finally:
        store.close()


def test_prepare_governance_raises_when_repository_project_mismatch(
    tmp_path: Path,
) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    other_root = tmp_path / "other_repo"
    other_root.mkdir()
    try:
        _register_default_ide_governance(
            state=state,
            root=root,
            store=store,
            key_hex=_VALID_KEY_HEX,
            client_version="0.3.0",
        )
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="project mismatch",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        with pytest.raises(
            MemoryContractError, match="project identity does not match"
        ):
            prepare_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(other_root),
                record_id=draft.id,
                decision="approve",
            )
    finally:
        store.close()


def test_commit_governance_raises_on_unsupported_protocol(tmp_path: Path) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        register_ide_governance(
            state,
            ide_governance_key=_VALID_KEY_HEX,
            client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
            client_version="0.3.0",
        )
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="protocol mismatch",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(_VALID_KEY_HEX),
            ticket_id=str(prepared["governance_ticket"]),
            record_id=draft.id,
            decision="approve",
            confirmation_nonce=nonce,
            project_id=project.id,  # type: ignore[attr-defined]
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        with pytest.raises(
            MemoryContractError, match="Unsupported ide_attestation protocol"
        ):
            commit_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(root),
                record_id=draft.id,
                decision="approve",
                governance_ticket=str(prepared["governance_ticket"]),
                confirmation_nonce=nonce,
                proof=proof,
                actor="vscode-test",
                protocol=IDE_GOVERNANCE_PROTOCOL_VERSION + 1,
            )
    finally:
        store.close()


def test_commit_governance_raises_on_ticket_record_id_mismatch(tmp_path: Path) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        register_ide_governance(
            state,
            ide_governance_key=_VALID_KEY_HEX,
            client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
            client_version="0.3.0",
        )
        draft1 = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="ticket for draft1",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        draft2 = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="ticket mismatch draft2",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft1.id,
            decision="approve",
        )
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(_VALID_KEY_HEX),
            ticket_id=str(prepared["governance_ticket"]),
            record_id=draft1.id,
            decision="approve",
            confirmation_nonce=nonce,
            project_id=project.id,  # type: ignore[attr-defined]
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        with pytest.raises(
            MemoryContractError,
            match="Governance ticket does not match the commit request",
        ):
            commit_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(root),
                record_id=draft2.id,
                decision="approve",
                governance_ticket=str(prepared["governance_ticket"]),
                confirmation_nonce=nonce,
                proof=proof,
                actor="vscode-test",
                protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
            )
    finally:
        store.close()


def test_commit_governance_raises_on_confirmation_nonce_mismatch(
    tmp_path: Path,
) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        register_ide_governance(
            state,
            ide_governance_key=_VALID_KEY_HEX,
            client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
            client_version="0.3.0",
        )
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="nonce mismatch",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        wrong_nonce = "deadbeef"
        proof = compute_governance_proof(
            bytes.fromhex(_VALID_KEY_HEX),
            ticket_id=str(prepared["governance_ticket"]),
            record_id=draft.id,
            decision="approve",
            confirmation_nonce=str(wrong_nonce),
            project_id=project.id,  # type: ignore[attr-defined]
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        with pytest.raises(
            MemoryContractError, match="confirmation_nonce does not match"
        ):
            commit_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(root),
                record_id=draft.id,
                decision="approve",
                governance_ticket=str(prepared["governance_ticket"]),
                confirmation_nonce=str(wrong_nonce),
                proof=proof,
                actor="vscode-test",
                protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
            )
    finally:
        store.close()


def test_commit_governance_ticket_errors_for_unknown_consumed_and_expired(
    tmp_path: Path,
) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        register_ide_governance(
            state,
            ide_governance_key=_VALID_KEY_HEX,
            client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
            client_version="0.3.0",
        )
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="ticket errors",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        ticket_id = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])

        proof = compute_governance_proof(
            bytes.fromhex(_VALID_KEY_HEX),
            ticket_id=ticket_id,
            record_id=draft.id,
            decision="approve",
            confirmation_nonce=nonce,
            project_id=project.id,  # type: ignore[attr-defined]
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )

        with pytest.raises(
            MemoryContractError, match="Unknown or expired governance ticket"
        ):
            commit_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(root),
                record_id=draft.id,
                decision="approve",
                governance_ticket="missing-ticket",
                confirmation_nonce=nonce,
                proof=proof,
                actor="vscode-test",
                protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
            )

        # Mark the ticket as consumed.
        state.tickets[ticket_id].consumed = True
        with pytest.raises(MemoryContractError, match="already used"):
            commit_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(root),
                record_id=draft.id,
                decision="approve",
                governance_ticket=ticket_id,
                confirmation_nonce=nonce,
                proof=proof,
                actor="vscode-test",
                protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
            )

        # Re-prepare to restore a non-consumed ticket and expire it.
        state.tickets[ticket_id].consumed = False
        state.tickets[ticket_id].expires_at_unix = time.time() - 10
        with pytest.raises(MemoryContractError, match="ticket expired"):
            commit_governance(
                state,
                store,
                project_id=project.id,  # type: ignore[attr-defined]
                root_path=str(root),
                record_id=draft.id,
                decision="approve",
                governance_ticket=ticket_id,
                confirmation_nonce=nonce,
                proof=proof,
                actor="vscode-test",
                protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
            )
    finally:
        store.close()


def test_commit_governance_actor_label_resolves_from_client_name_and_version(
    tmp_path: Path,
) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        register_ide_governance(
            state,
            ide_governance_key=_VALID_KEY_HEX,
            client_name=next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS)),
            client_version="0.3.0",
        )
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="actor label uses version",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        ticket_id = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(_VALID_KEY_HEX),
            ticket_id=ticket_id,
            record_id=draft.id,
            decision="approve",
            confirmation_nonce=nonce,
            project_id=project.id,  # type: ignore[attr-defined]
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        committed = commit_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
            governance_ticket=ticket_id,
            confirmation_nonce=nonce,
            proof=proof,
            actor="",  # empty => use _resolve_client_label
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        assert committed["status"] == "ok"
        updated = store.find_record(draft.id)
        assert updated is not None
        assert updated.approved_by is not None
        assert updated.approved_by.endswith("/0.3.0")
    finally:
        store.close()


def test_commit_governance_actor_label_resolves_without_version(tmp_path: Path) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        client_name = next(iter(IDE_GOVERNANCE_ALLOWED_CLIENTS))
        register_ide_governance(
            state,
            ide_governance_key=_VALID_KEY_HEX,
            client_name=client_name,
            client_version=None,
        )
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="actor label uses only name",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
        )
        ticket_id = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(_VALID_KEY_HEX),
            ticket_id=ticket_id,
            record_id=draft.id,
            decision="approve",
            confirmation_nonce=nonce,
            project_id=project.id,  # type: ignore[attr-defined]
            statement_digest=str(prepared["statement_digest"]),
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        commit_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
            governance_ticket=ticket_id,
            confirmation_nonce=nonce,
            proof=proof,
            actor="",  # empty => use _resolve_client_label
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        updated = store.find_record(draft.id)
        assert updated is not None
        assert updated.approved_by == client_name
    finally:
        store.close()


def test_commit_governance_rejected_when_channel_disabled(tmp_path: Path) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=False,
    )
    try:
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="channel disabled",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        payload = commit_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
            governance_ticket="whatever",
            confirmation_nonce="nonce",
            proof="0" * 64,
            actor="vscode-test",
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
        assert payload["status"] == "rejected"
        assert payload["action"] == "commit_governance"
    finally:
        store.close()


def test_commit_governance_rate_limit_rejects_without_mutation(
    tmp_path: Path,
) -> None:
    root, project, store, state = _make_store_project_and_state(
        tmp_path=tmp_path,
        channel_enabled=True,
    )
    try:
        draft = record_candidate(
            store,
            project=project,  # type: ignore[arg-type]
            record_type="change_rationale",
            statement="rate limited draft",
            subject_path="pkg/mod.py",
            max_candidates=10,
        )
        _register_default_ide_governance(
            state=state,
            root=root,
            store=store,
            key_hex=_VALID_KEY_HEX,
            client_version="0.3.0",
        )
        state.commit_attempts = IDE_GOVERNANCE_MAX_COMMIT_ATTEMPTS

        payload = commit_governance(
            state,
            store,
            project_id=project.id,  # type: ignore[attr-defined]
            root_path=str(root),
            record_id=draft.id,
            decision="approve",
            governance_ticket="whatever",
            confirmation_nonce="nonce",
            proof="0" * 64,
            actor="vscode-test",
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )

        assert payload["status"] == "rejected"
        assert payload["reason"] == "governance_rate_limited"
        assert state.commit_attempts == IDE_GOVERNANCE_MAX_COMMIT_ATTEMPTS
        unchanged = store.find_record(draft.id)
        assert unchanged is not None
        assert unchanged.status == "draft"
    finally:
        store.close()
