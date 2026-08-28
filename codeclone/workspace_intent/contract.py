# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Surface-neutral workspace intent record and integrity contract.

The record's own contract is also where the record says what may be read out
of it. :func:`audit_scope_payload` is the forensic projection of a scope that
is already written -- the counterpart of
:mod:`codeclone.contracts.scope_grammar`, which governs scopes that are being
written now. Both halves answer the same subject and neither may answer the
other's question.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, NamedTuple

from ..cache.integrity import canonical_json
from ..contracts.scope_grammar import (
    SCOPE_ENTRY_EMPTY,
    ExactFile,
    ScopeGrammarError,
    entry_contains_path,
    parse_scope_entry,
)
from ..utils.coerce import as_mapping as _as_mapping

LEGACY_REGISTRY_VERSION: Final = "1"
REGISTRY_VERSION: Final = "2"
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

    def unsigned_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "registry_version": REGISTRY_VERSION,
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
        return payload


#: An entry the current grammar cannot read. Stable token; callers branch on it.
LEGACY_AMBIGUOUS: Final = "legacy_ambiguous"

#: An entry the current grammar reads. Stable token.
CURRENT_GRAMMAR: Final = "current"

#: The three pre-grammar consumers were measured to read this form identically.
HISTORICAL_UNAMBIGUOUS: Final = "unambiguous"

#: They were measured to read this form differently from one another.
HISTORICAL_PRODUCER_SPECIFIC: Final = "producer_specific"

#: Optional record field naming the consumer whose reading a record preserves.
#:
#: Measured on the live registry 2026-08-28: no producer writes it. All 733
#: rows carry the same nineteen top-level keys and ``registry_version`` ``"2"``,
#: the 76 glob-bearing rows included, so the version is not a discriminator
#: either; and every one of the 174 ``intent.*`` audit events carries
#: ``surface='unknown'`` with a null ``tool_name``. The reader therefore
#: answers ``None`` on every record that exists today, which is the point: the
#: "show its then-interpretation" branch has no input, and inventing one would
#: be the same offence as re-deciding the entry.
SCOPE_INTERPRETER_FIELD: Final = "scope_interpreter"

#: Characters that make a stored string a pattern rather than a path.
_METACHARACTERS: Final[frozenset[str]] = frozenset("*?[]")

_LEGACY_NEXT_STEP: Final = (
    "read this entry as the raw text it stores; it predates the allowed_files "
    "grammar and no current-grammar reading of it is evidence of what it "
    "authorised. To decide a new write, declare a new scope."
)

_RECORD_LEGACY_NEXT_STEP: Final = (
    "this record's scope holds an entry written before the allowed_files "
    "grammar; report it verbatim and do not derive an in-scope or out-of-scope "
    "verdict from it. Closed intents never authorise a write again, so there "
    "is nothing to migrate."
)


class ScopeRelation(str, Enum):
    """What an audit may say about one path and one already-written scope."""

    #: Every known reading of the scope covered the path.
    INSIDE = "inside"
    #: Every known reading of the scope excluded the path.
    OUTSIDE = "outside"
    #: The readings disagreed, or the entry is unreadable now. No verdict.
    LEGACY_AMBIGUOUS = LEGACY_AMBIGUOUS


#: Strongest first. A positive fact from one entry settles a scope its
#: neighbour cannot answer for; an unknown outranks a negative, because
#: "nothing covered it" is only true when nothing *could* have.
_RELATION_STRENGTH: Final[tuple[ScopeRelation, ...]] = (
    ScopeRelation.INSIDE,
    ScopeRelation.LEGACY_AMBIGUOUS,
    ScopeRelation.OUTSIDE,
)


class AuditScopeEntry(NamedTuple):
    """One persisted scope entry, read without being re-decided."""

    #: Exactly the stored text. Never stripped, re-slashed or canonicalised:
    #: rewriting ``./pkg/b.py`` to ``pkg/b.py`` would make the record's
    #: ``scope_digest`` disagree with the scope its producer wrote.
    raw: str
    status: str
    kind: str | None
    refusal_reason: str | None
    historical_reading: str
    interpreter: str | None
    next_step: str | None

    @property
    def is_legacy(self) -> bool:
        return self.status == LEGACY_AMBIGUOUS

    def to_payload(self) -> dict[str, object]:
        """The entry as an audit reports it: raw text and status, no verdict."""

        return {
            "raw": self.raw,
            "status": self.status,
            "kind": self.kind,
            "refusal_reason": self.refusal_reason,
            "historical_reading": self.historical_reading,
            "interpreter": self.interpreter,
        }


def scope_interpreter_from_record(payload: Mapping[str, object]) -> str | None:
    """The consumer whose reading this record preserves, if it names one.

    Returns ``None`` for every record written to date -- see
    :data:`SCOPE_INTERPRETER_FIELD`. Reporting the absence is the contract; a
    caller that gets ``None`` has learned a fact, not lost one.
    """

    value = payload.get(SCOPE_INTERPRETER_FIELD)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def read_audit_scope_entry(
    text: str,
    *,
    interpreter: str | None = None,
) -> AuditScopeEntry:
    """Read one persisted entry for audit. Total: it refuses nothing."""

    raw = str(text)
    try:
        parsed = parse_scope_entry(raw)
    except ScopeGrammarError as refusal:
        return AuditScopeEntry(
            raw=raw,
            status=LEGACY_AMBIGUOUS,
            kind=None,
            refusal_reason=refusal.reason,
            historical_reading=HISTORICAL_PRODUCER_SPECIFIC,
            interpreter=interpreter,
            next_step=_LEGACY_NEXT_STEP,
        )
    historical = (
        HISTORICAL_UNAMBIGUOUS
        if isinstance(parsed, ExactFile)
        else HISTORICAL_PRODUCER_SPECIFIC
    )
    return AuditScopeEntry(
        raw=raw,
        status=CURRENT_GRAMMAR,
        kind=parsed.kind.value,
        refusal_reason=None,
        historical_reading=historical,
        interpreter=interpreter,
        next_step=None,
    )


def read_audit_scope(
    texts: Iterable[str],
    *,
    interpreter: str | None = None,
) -> tuple[AuditScopeEntry, ...]:
    """Read a persisted scope for audit, entry for entry, dropping nothing.

    The live reader drops blanks because a blank cannot authorise a write. An
    audit that drops one has silently shortened the record it is reporting.
    """

    return tuple(
        read_audit_scope_entry(text, interpreter=interpreter) for text in texts
    )


def _literal_head(raw: str) -> str:
    """The longest prefix of ``raw`` that no pattern reading can escape.

    ``fnmatchcase`` cannot match left of the first metacharacter and neither
    can a directory prefix, so a path that does not start with this text was
    outside the entry under every reading the pre-grammar consumers had. That
    is what keeps :data:`ScopeRelation.OUTSIDE` reachable for a legacy entry
    instead of collapsing the whole audit into "unknown".
    """

    normalised = raw.replace("\\", "/").strip()
    for index, char in enumerate(normalised):
        if char in _METACHARACTERS:
            return normalised[:index]
    return normalised


def _entry_relation(entry: AuditScopeEntry, path: str) -> ScopeRelation:
    """Relation of one entry to one path. Total over the closed entry forms."""

    if entry.is_legacy:
        if entry.refusal_reason == SCOPE_ENTRY_EMPTY:
            # Nothing named nothing: every reading excluded every path.
            return ScopeRelation.OUTSIDE
        # Never ``INSIDE``: a positive claim derived from an entry this
        # grammar cannot read would be the verdict the ruling forbids. Only
        # the negative survives, and only where every reading agreed on it.
        if path.startswith(_literal_head(entry.raw)):
            return ScopeRelation.LEGACY_AMBIGUOUS
        return ScopeRelation.OUTSIDE
    if not entry_contains_path(parse_scope_entry(entry.raw), path):
        # Outside the entry every reading agreed, prefix and glob included.
        return ScopeRelation.OUTSIDE
    # Inside it they did not. Only the form they all read alike still answers,
    # which is why ``historical_reading`` decides here instead of being a field
    # the payload reports and nothing consults.
    if entry.historical_reading == HISTORICAL_UNAMBIGUOUS:
        return ScopeRelation.INSIDE
    return ScopeRelation.LEGACY_AMBIGUOUS


def audit_scope_relation(
    texts: Sequence[str],
    path: str,
    *,
    interpreter: str | None = None,
) -> ScopeRelation:
    """What an audit may say about ``path`` and an already-written scope.

    Returns :data:`ScopeRelation.LEGACY_AMBIGUOUS` rather than a verdict
    wherever the readings this record could have been written under disagree.
    """

    relations = {
        _entry_relation(entry, path)
        for entry in read_audit_scope(texts, interpreter=interpreter)
    }
    for candidate in _RELATION_STRENGTH:
        if candidate in relations:
            return candidate
    # An empty scope authorised nothing, and every reading agreed on that.
    return ScopeRelation.OUTSIDE


def _scope_field(scope: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = scope.get(key, ())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value)
    return ()


def audit_scope_payload(
    scope: Mapping[str, object],
    *,
    interpreter: str | None = None,
) -> dict[str, object]:
    """The audit projection of a persisted scope, verdict-free by construction.

    Sits beside the raw ``scope`` in the record payload rather than replacing
    it: rule one is that the stored text survives untouched, and a reader that
    only ever saw a projection could not check that.
    """

    fields = {
        key: read_audit_scope(_scope_field(scope, key), interpreter=interpreter)
        for key in ("allowed_files", "allowed_related")
    }
    legacy = [
        entry for entries in fields.values() for entry in entries if entry.is_legacy
    ]
    payload: dict[str, object] = {
        "status": LEGACY_AMBIGUOUS if legacy else CURRENT_GRAMMAR,
        "legacy_entry_count": len(legacy),
        "interpreter": interpreter,
    }
    for key, entries in fields.items():
        payload[key] = [entry.to_payload() for entry in entries]
    if legacy:
        payload["historical_interpretation"] = HISTORICAL_PRODUCER_SPECIFIC
        payload["refusal_reasons"] = sorted(
            {str(entry.refusal_reason) for entry in legacy}
        )
        payload["next_step"] = _RECORD_LEGACY_NEXT_STEP
    return payload


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
    "CURRENT_GRAMMAR",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "HISTORICAL_PRODUCER_SPECIFIC",
    "HISTORICAL_UNAMBIGUOUS",
    "LEGACY_AMBIGUOUS",
    "LEGACY_REGISTRY_VERSION",
    "MAX_LEASE_SECONDS",
    "MAX_TTL_SECONDS",
    "MIN_LEASE_SECONDS",
    "MIN_TTL_SECONDS",
    "REGISTRY_VERSION",
    "SCOPE_INTERPRETER_FIELD",
    "AuditScopeEntry",
    "ScopeRelation",
    "WorkspaceIntentRecord",
    "audit_scope_payload",
    "audit_scope_relation",
    "compute_intent_digest",
    "compute_scope_digest",
    "read_audit_scope",
    "read_audit_scope_entry",
    "scope_interpreter_from_record",
    "verify_intent_integrity",
]
