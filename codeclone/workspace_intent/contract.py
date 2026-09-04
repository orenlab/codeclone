# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Surface-neutral workspace intent record and integrity contract.

The record, its digests and its integrity check live here. How a scope this
record already holds may be *read* does not: that owner is
:mod:`codeclone.contracts.legacy_scope` in ring r0, beside the
:mod:`codeclone.contracts.scope_grammar` door that governs the scopes being
written now. Both readers have consumers in r2p and r4, which share only r0
and r1, so an answer stated here would have to be restated there.

**What reading one stored document yields** is owned here, in
:class:`WorkspaceDocumentRead`, and the ring follows the same rule read the
other way. That answer names a :class:`WorkspaceIntentRecord` in one of its
arms, and this module is the record's owner; r0 and r1 are lower but may not
name an r2p type, so no ring below this one can hold the concept without a
back-edge. r2p is therefore the lowest valid owner, and within it this module
is the one that already owns *both* things the answer discriminates between:
the record, and the ``integrity.payload_sha256`` witness that decides whether
a document this build cannot model was nevertheless written whole.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final, NamedTuple

from ..cache.integrity import canonical_json
from ..models import BeforeExecutionWitness
from ..utils.coerce import as_mapping as _as_mapping

# The first generation: no lease, no report digest.  Its name is load-bearing
# in :mod:`.models`, where it still selects the lease-defaulting read.
LEGACY_REGISTRY_VERSION: Final = "1"
# The second: lease and report digest, and nothing about the reading of the
# source that produced the report.  ``run_id`` names a report, and several
# executions may have stated it, so a record of this generation cannot say
# WHICH execution its intent was declared on.  Kept as a name because that
# inability is now a typed outcome rather than a silent default.
WITNESSLESS_REGISTRY_VERSION: Final = "2"
# The third: the before-execution witness, content-bound (RULING-2026-09-02).
REGISTRY_VERSION: Final = "3"
DEFAULT_TTL_SECONDS: Final = 3600
MIN_TTL_SECONDS: Final = 60
MAX_TTL_SECONDS: Final = 86400
DEFAULT_LEASE_SECONDS: Final = 300
MIN_LEASE_SECONDS: Final = 60
MAX_LEASE_SECONDS: Final = 600
_HEX_DIGEST_LENGTH: Final = 64
_SAFE_INTENT_ID_RE: Final = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class WorkspaceIntentRecord:
    intent_id: str
    agent_pid: int
    agent_start_epoch: int
    agent_label: str
    run_id: str
    declared_at_utc: str
    expires_at_utc: str
    ttl_seconds: int
    status: str
    intent: str
    scope: dict[str, object]
    scope_digest: str
    blast_radius_summary: dict[str, object]
    lease_renewed_at_utc: str
    lease_seconds: int
    report_digest: str
    dirty_snapshot: dict[str, object] | None = None
    before_execution: BeforeExecutionWitness | None = None

    @property
    def written_registry_version(self) -> str:
        """The generation this record serialises as, derived from its witness.

        Provenance, never authority: it says what the reader will find on the
        wire, and a record read back from an older generation reports the
        generation it has become in memory, not the one it was born in.
        """

        return (
            REGISTRY_VERSION
            if self.before_execution is not None
            else WITNESSLESS_REGISTRY_VERSION
        )

    def unsigned_payload(self) -> dict[str, object]:
        # The version is the wire fact that a witness is there to be read, so
        # it is derived from the witness rather than stamped beside it. A
        # record with nothing to bind is honestly of the older generation --
        # and is refused as such on the recovery path.
        payload: dict[str, object] = {
            "registry_version": self.written_registry_version,
            "intent_id": self.intent_id,
            "agent_pid": self.agent_pid,
            "agent_start_epoch": self.agent_start_epoch,
            "agent_label": self.agent_label,
            "run_id": self.run_id,
            "declared_at_utc": self.declared_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "ttl_seconds": self.ttl_seconds,
            "status": self.status,
            "intent": self.intent,
            "scope": self.scope,
            "scope_digest": self.scope_digest,
            "blast_radius_summary": self.blast_radius_summary,
            "lease_renewed_at_utc": self.lease_renewed_at_utc,
            "lease_seconds": self.lease_seconds,
            "report_digest": self.report_digest,
        }
        if self.dirty_snapshot is not None:
            payload["dirty_snapshot"] = self.dirty_snapshot
        if self.before_execution is not None:
            payload["before_execution"] = self.before_execution.to_payload()
        return payload


class WorkspaceDocumentReadKind(str, Enum):
    """What this build got out of one stored registry document.

    A closed vocabulary rather than "a record, or one of some strings". The
    rejected shape was ``WorkspaceIntentRecord | UnreadableReason``, read by
    ``isinstance``: correct on the day it was written, and load-bearing on the
    coincidence that a record is never a string. A tag survives a state the
    union cannot -- every reader branches on a declared name, and a reader
    that has no rule for a new one says so instead of falling through.
    """

    #: The document became a record. The only arm that carries one.
    RECORD = "record"
    #: Nothing is stored at the address that was asked about. Produced by a
    #: lookup by intent id, never by reading bytes that are already in hand.
    ABSENT = "absent"
    #: Bytes attributable to no writer: not JSON, not an object, no digest, or
    #: a value edited under a digest that no longer covers it. Removing them
    #: is hygiene.
    CORRUPT = "registry_record_corrupt"
    #: A document some writer produced whole and signed, carrying a field, a
    #: generation or a status token this build has never heard of. Unreadable
    #: HERE and live coordination state everywhere else. Refusing to
    #: understand it is honest; destroying it, or treating it as absent, is
    #: not.
    INCOMPATIBLE = "registry_record_unreadable_by_this_build"


class WorkspaceDocumentRead(NamedTuple):
    """The outcome of reading one stored workspace intent document.

    One named contract with one owner, because reading a stored payload has
    genuinely more than two outcomes and the extra ones are domain states, not
    error strings.

    The invariant is that ``record`` is present exactly on
    :attr:`WorkspaceDocumentReadKind.RECORD`.  The three record-less arms hold
    it by construction -- the field defaults to ``None`` and naming the kind is
    the whole of building one -- and the fourth has :meth:`of_record` as its
    only constructor, so the one arm that can violate the invariant has one
    place that decides it.
    """

    kind: WorkspaceDocumentReadKind
    record: WorkspaceIntentRecord | None = None

    @classmethod
    def of_record(cls, record: WorkspaceIntentRecord) -> WorkspaceDocumentRead:
        return cls(kind=WorkspaceDocumentReadKind.RECORD, record=record)


def compute_scope_digest(scope: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(scope)).encode("utf-8")).hexdigest()


def compute_intent_digest(data: Mapping[str, object]) -> str:
    digestable = {key: value for key, value in data.items() if key != "integrity"}
    return hashlib.sha256(canonical_json(digestable).encode("utf-8")).hexdigest()


def _is_hex_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) != _HEX_DIGEST_LENGTH:
        return False
    return all(char in "0123456789abcdef" for char in value.lower())


def verify_intent_integrity(data: Mapping[str, object]) -> bool:
    integrity = _as_mapping(data.get("integrity"))
    stored = integrity.get("payload_sha256")
    if not _is_hex_digest(stored):
        return False
    expected = compute_intent_digest(data)
    return hmac.compare_digest(str(stored), expected)


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "LEGACY_REGISTRY_VERSION",
    "MAX_LEASE_SECONDS",
    "MAX_TTL_SECONDS",
    "MIN_LEASE_SECONDS",
    "MIN_TTL_SECONDS",
    "REGISTRY_VERSION",
    "WITNESSLESS_REGISTRY_VERSION",
    "BeforeExecutionWitness",
    "WorkspaceDocumentRead",
    "WorkspaceDocumentReadKind",
    "WorkspaceIntentRecord",
    "compute_intent_digest",
    "compute_scope_digest",
    "verify_intent_integrity",
]
