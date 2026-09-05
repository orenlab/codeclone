# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Which wire generations the IDE governance channel answers, and why.

Admission is decided by MEMBERSHIP in a declared set, never by arithmetic
over the latest version. The difference is invisible today -- ``{2, 3}`` and
``2 <= p <= LATEST`` accept exactly the same integers -- and becomes a
silent hole the day LATEST moves to 4. So the pin here reaches the RULE:
it makes 4 the latest version and asks whether 4 became admissible.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest

from codeclone.memory import ide_governance
from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import (
    STATEMENT_ORIGIN_HUMAN_AMENDED,
    record_candidate,
)
from codeclone.memory.ide_governance import (
    AMEND_AND_APPROVE,
    GOVERNANCE_DECISION_PROTOCOL_CODE,
    GOVERNANCE_UNSUPPORTED_PROTOCOL_CODE,
    IDE_GOVERNANCE_AMENDMENT_PROTOCOLS,
    IDE_GOVERNANCE_PROTOCOL_VERSION,
    IDE_GOVERNANCE_SUPPORTED_PROTOCOLS,
    IdeGovernanceSessionState,
    commit_governance,
    compute_governance_proof,
    prepare_governance,
    register_ide_governance,
)
from codeclone.memory.models import MemoryRecord
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore

_HELP_TOPIC = 'help(topic="engineering_memory")'


class _Channel:
    """One registered IDE governance channel over one store."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.project = resolve_project_identity(self.root)
        self.store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
        self.store.initialize(self.project)
        self.state = IdeGovernanceSessionState(channel_enabled=True)
        self.key_hex = secrets.token_hex(32)
        self.registered = register_ide_governance(
            self.state,
            ide_governance_key=self.key_hex,
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )
        self._drafts = 0

    def draft(self) -> MemoryRecord:
        self._drafts += 1
        return record_candidate(
            self.store,
            project=self.project,
            record_type="architecture_decision",
            statement=f"Governance draft {self._drafts} awaiting human review.",
            subject_path=f"pkg/mod{self._drafts}.py",
            max_candidates=100,
        )

    def commit(
        self,
        *,
        record_id: str,
        decision: str,
        protocol: int,
        statement: str | None = None,
    ) -> dict[str, object]:
        prepared = prepare_governance(
            self.state,
            self.store,
            project_id=self.project.id,
            root_path=str(self.root),
            record_id=record_id,
            decision=decision,
        )
        ticket = str(prepared["governance_ticket"])
        nonce = str(prepared["confirmation_nonce"])
        proof = compute_governance_proof(
            bytes.fromhex(self.key_hex),
            ticket_id=ticket,
            record_id=record_id,
            decision=decision,
            confirmation_nonce=nonce,
            project_id=self.project.id,
            statement_digest=str(prepared["statement_digest"]),
            protocol=protocol,
        )
        return commit_governance(
            self.state,
            self.store,
            project_id=self.project.id,
            root_path=str(self.root),
            record_id=record_id,
            decision=decision,
            governance_ticket=ticket,
            confirmation_nonce=nonce,
            proof=proof,
            actor="vscode-human",
            protocol=protocol,
            statement=statement,
        )

    def settled(self, record_id: str) -> MemoryRecord:
        found = self.store.find_record(record_id)
        assert found is not None
        return found

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def channel(tmp_path: Path) -> Iterator[_Channel]:
    made = _Channel(tmp_path)
    try:
        yield made
    finally:
        made.close()


def _assert_typed_refusal(message: str, *, code: str) -> None:
    """A typed outcome is a code, an executable next_step and a help topic."""
    assert message.startswith(f"{code}: "), message
    assert " next_step: " in message, message
    assert _HELP_TOPIC in message, message


# ── the supported set ────────────────────────────────────────────────────


def test_latest_generation_is_three_and_lives_inside_the_supported_set() -> None:
    # 3 is the generation the maintainer ratified for the amendment bridge.
    assert IDE_GOVERNANCE_PROTOCOL_VERSION == 3
    # Self-consistency, so a future bump that forgets the set fails loudly
    # instead of making the server refuse its own advertised version.
    assert IDE_GOVERNANCE_PROTOCOL_VERSION in IDE_GOVERNANCE_SUPPORTED_PROTOCOLS
    assert max(IDE_GOVERNANCE_SUPPORTED_PROTOCOLS) == IDE_GOVERNANCE_PROTOCOL_VERSION
    assert IDE_GOVERNANCE_AMENDMENT_PROTOCOLS <= IDE_GOVERNANCE_SUPPORTED_PROTOCOLS


def test_register_handshake_advertises_latest_and_the_whole_supported_set(
    channel: _Channel,
) -> None:
    assert channel.registered["protocol"] == IDE_GOVERNANCE_PROTOCOL_VERSION
    # A list, not a set: the wire is ordered, and an unsorted set would make
    # the handshake non-deterministic between runs.
    assert channel.registered["supported_protocols"] == sorted(
        IDE_GOVERNANCE_SUPPORTED_PROTOCOLS
    )


def test_the_handshake_orders_the_set_ascending(
    channel: _Channel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordering claim, given a population that can refute it.

    ``sorted()`` and bare ``list()`` are indistinguishable over the live set:
    ``list(frozenset({2, 3}))`` is already ``[2, 3]``, so no assertion about
    the real handshake can tell them apart -- a green ordering test there
    would be theatre. ``frozenset({2, 3, 9})`` iterates ``[9, 2, 3]``, which
    is the distinguishing case, so the pin is made against it.
    """
    unordered = frozenset({2, 3, 9})
    assert list(unordered) != sorted(unordered), "positive control lost its bite"
    monkeypatch.setattr(
        ide_governance,
        "IDE_GOVERNANCE_SUPPORTED_PROTOCOLS",
        unordered,
    )
    state = IdeGovernanceSessionState(channel_enabled=True)
    registered = register_ide_governance(
        state,
        ide_governance_key=channel.key_hex,
        client_name="CodeClone VS Code",
        client_version="0.3.0",
    )
    assert registered["supported_protocols"] == [2, 3, 9]


def test_admission_is_membership_over_a_scanned_window(channel: _Channel) -> None:
    """Accepted iff a member. Off-by-one and widened sets die here."""
    admitted: set[int] = set()
    for protocol in range(6):
        draft = channel.draft()
        try:
            channel.commit(
                record_id=draft.id,
                decision="approve",
                protocol=protocol,
            )
        except MemoryContractError as exc:
            _assert_typed_refusal(
                str(exc),
                code=GOVERNANCE_UNSUPPORTED_PROTOCOL_CODE,
            )
            continue
        admitted.add(protocol)
    assert admitted == set(IDE_GOVERNANCE_SUPPORTED_PROTOCOLS)


def test_a_future_generation_is_not_admitted_by_being_the_latest(
    channel: _Channel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The maintainer's concern, made falsifiable.

    Membership and ``2 <= p <= LATEST`` are extensionally identical while
    LATEST is 3, so no ordinary test can tell them apart. Move LATEST to a
    hypothetical 4 without adding 4 to the supported set: arithmetic admits
    it, membership does not. Mutating the check to a range reddens exactly
    this test.
    """
    monkeypatch.setattr(ide_governance, "IDE_GOVERNANCE_PROTOCOL_VERSION", 4)
    draft = channel.draft()
    with pytest.raises(MemoryContractError) as excinfo:
        channel.commit(record_id=draft.id, decision="approve", protocol=4)
    _assert_typed_refusal(str(excinfo.value), code=GOVERNANCE_UNSUPPORTED_PROTOCOL_CODE)
    assert channel.settled(draft.id).status == "draft"


# ── v2 clients keep working ──────────────────────────────────────────────


def test_a_v2_client_still_approves_end_to_end(channel: _Channel) -> None:
    draft = channel.draft()
    committed = channel.commit(record_id=draft.id, decision="approve", protocol=2)
    assert committed["status"] == "ok"
    assert committed["record_status"] == "active"
    assert channel.settled(draft.id).status == "active"


def test_a_v2_client_still_rejects_and_archives(channel: _Channel) -> None:
    rejected = channel.draft()
    assert (
        channel.commit(record_id=rejected.id, decision="reject", protocol=2)["status"]
        == "ok"
    )
    published = channel.draft()
    channel.commit(record_id=published.id, decision="approve", protocol=2)
    archived = channel.commit(
        record_id=published.id,
        decision="archive",
        protocol=2,
    )
    assert archived["record_status"] == "archived"


# ── amendment is a generation-3 decision ─────────────────────────────────


def test_amend_and_approve_at_v2_refuses_as_a_version_problem(
    channel: _Channel,
) -> None:
    """Version-shaped, not spelling-shaped.

    ``amend_and_approve`` is spelled correctly; the client's wire is too old.
    Reporting it as an unknown decision would send the reader to check the
    spelling of a word that is already right.
    """
    draft = channel.draft()
    with pytest.raises(MemoryContractError) as excinfo:
        channel.commit(
            record_id=draft.id,
            decision=AMEND_AND_APPROVE,
            protocol=2,
            statement="Human-corrected wording.",
        )
    message = str(excinfo.value)
    _assert_typed_refusal(message, code=GOVERNANCE_DECISION_PROTOCOL_CODE)
    assert "Unknown governance decision" not in message
    assert str(sorted(IDE_GOVERNANCE_AMENDMENT_PROTOCOLS)[0]) in message
    # Nothing was written: the draft still holds its own wording.
    settled = channel.settled(draft.id)
    assert settled.status == "draft"
    assert settled.statement == draft.statement


def test_the_two_refusals_are_distinguishable(channel: _Channel) -> None:
    """A too-old wire and an unsupported wire are different remedies."""
    old_wire = channel.draft()
    with pytest.raises(MemoryContractError) as amendment:
        channel.commit(
            record_id=old_wire.id,
            decision=AMEND_AND_APPROVE,
            protocol=2,
            statement="Human-corrected wording.",
        )
    unsupported = channel.draft()
    with pytest.raises(MemoryContractError) as version:
        channel.commit(record_id=unsupported.id, decision="approve", protocol=1)
    # The codes differ by construction -- mypy rejects comparing them as a
    # non-overlapping equality -- so what is worth pinning is that each
    # refusal actually WEARS its own code.
    _assert_typed_refusal(str(amendment.value), code=GOVERNANCE_DECISION_PROTOCOL_CODE)
    _assert_typed_refusal(
        str(version.value),
        code=GOVERNANCE_UNSUPPORTED_PROTOCOL_CODE,
    )


def test_an_unknown_decision_is_still_an_unknown_decision(channel: _Channel) -> None:
    """The complement: a misspelling at a good protocol must NOT read as a
    version problem, or the new gate has simply swallowed the old one."""
    draft = channel.draft()
    with pytest.raises(MemoryContractError) as excinfo:
        channel.commit(
            record_id=draft.id,
            decision="amend",
            protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
        )
    message = str(excinfo.value)
    assert "Unknown governance decision" in message
    assert GOVERNANCE_DECISION_PROTOCOL_CODE not in message


def test_amend_and_approve_succeeds_at_v3_and_the_receipt_names_its_wire(
    channel: _Channel,
) -> None:
    draft = channel.draft()
    committed = channel.commit(
        record_id=draft.id,
        decision=AMEND_AND_APPROVE,
        protocol=3,
        statement="Human-corrected wording for the published claim.",
    )
    assert committed["status"] == "ok"
    assert committed["record_status"] == "active"
    assert committed["statement_origin"] == STATEMENT_ORIGIN_HUMAN_AMENDED
    receipt = committed["proof"]
    assert isinstance(receipt, dict)
    # The receipt is bound to the contract generation that produced it: the
    # same bytes read back under another generation are a different claim.
    assert receipt["protocol"] == 3
    assert receipt["operation"] == AMEND_AND_APPROVE
    settled = channel.settled(draft.id)
    assert settled.statement == "Human-corrected wording for the published claim."


def test_a_plain_approve_receipt_carries_no_amendment_proof(
    channel: _Channel,
) -> None:
    """Probe validity for the receipt pin: `proof` rides amendments only, so
    a green `protocol` assertion above cannot be coming from somewhere else."""
    draft = channel.draft()
    committed = channel.commit(
        record_id=draft.id,
        decision="approve",
        protocol=IDE_GOVERNANCE_PROTOCOL_VERSION,
    )
    assert "proof" not in committed
