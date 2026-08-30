# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one owner of how an **already-written** scope entry may be read.

:mod:`codeclone.contracts.scope_grammar` governs the scopes being written now:
its door accepts an exact file or a directory prefix and refuses everything
else. This module governs the other half -- text that is already in the
registry, written under a door that no longer exists -- and the two halves may
never answer each other's question.

Ring r0 for the same reason the grammar is: the readers live in r2p
(``workspace_intent``, ``controller_insights``, ``audit``) and r4 (the MCP
surface), and ``r2p -> {r0, r1, r2p}`` with ``r4 -> {r0, r1, r3, r4}`` share
only r0 and r1. A shared answer therefore lives here or is restated once per
ring, and restating it is the defect this module exists to close. The audit
lane calls this owner; it does not grow a grammar of its own.

**The third form.** The write-authority union stays two-membered
(``ExactFile | DirectoryTree``) because those are the only forms that may
authorise a write. Reading what is already stored needs a third:

.. code-block:: text

    LegacyScope(raw, generation, interpretation)

``raw`` is the stored bytes, untouched. ``generation`` says which declaration
door could have emitted those bytes. ``interpretation`` says how much may be
said about the reading they had.

**No positive verdict survives an unreadable entry.** Ratified 2026-08-28: a
parser governs new decisions and gains no right to change, after the fact,
what already-written evidence meant. :func:`_legacy_scope_relation` therefore
has no ``INSIDE`` in it at all -- the impossibility is structural, not a branch
that happens not to be taken.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Final, NamedTuple, TypeAlias

from .scope_grammar import (
    SCOPE_ENTRY_EMPTY,
    AllowedScopeEntry,
    ExactFile,
    ScopeGrammarError,
    entry_contains_path,
    parse_scope_entry,
)

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
#: Measured on the live registry 2026-08-30: no producer writes it. All 740
#: rows carry the same nineteen top-level keys and ``registry_version`` ``"2"``,
#: the 76 glob-bearing rows included, so the version is not a discriminator
#: either; and every one of the ``intent.*`` audit events carries
#: ``surface='unknown'`` with a null ``tool_name``. The reader therefore
#: answers ``None`` on every record that exists today, which is the point: the
#: "show its then-interpretation" branch has no input, and inventing one would
#: be the same offence as re-deciding the entry.
SCOPE_INTERPRETER_FIELD: Final = "scope_interpreter"

#: Characters that make a stored string a pattern rather than a path.
_METACHARACTERS: Final[frozenset[str]] = frozenset("*?[]")

#: The function that answers for an unreadable entry, named so a structural
#: test can find it and prove ``INSIDE`` never appears inside it.
LEGACY_RELATION_FUNCTION: Final = "_legacy_scope_relation"


class ScopeGeneration(str, Enum):
    """Which declaration door could have emitted a stored entry's bytes.

    This is a deduction from the two doors, not provenance recovered from the
    record: measured on the live registry, **no** persisted field names a
    generation, a reader or a producing surface, and ``registry_version`` is
    ``"2"`` on every row including every glob-bearing one. What can be decided
    without inventing anything is narrower and still useful -- whether a door
    exists that emits this exact text.
    """

    #: The pre-grammar door emitted it and today's door refuses it, so the
    #: entry was a live scope entry once, read by the pre-grammar consumers.
    PRE_GRAMMAR = "pre_grammar"
    #: Neither door emits it. The text entered the registry past the door, so
    #: no consumer's reading of it was ever exercised.
    NO_DECLARATION_DOOR = "no_declaration_door"


class ScopeInterpretation(str, Enum):
    """How much may be said about the reading a stored entry had."""

    #: The readings diverged and nothing names whose applies.
    AMBIGUOUS = "ambiguous"
    #: The readings diverged and the record names the consumer that decided.
    PRODUCER_SPECIFIC = "producer_specific"
    #: Every reading agreed, so the audit may answer from the reading itself.
    KNOWN = "known"


class ScopeRelation(str, Enum):
    """What an audit may say about one path and one already-written scope."""

    #: Every known reading of the scope covered the path.
    INSIDE = "inside"
    #: Every known reading of the scope excluded the path.
    OUTSIDE = "outside"
    #: The readings disagreed, or the entry is unreadable now. No verdict.
    LEGACY_AMBIGUOUS = LEGACY_AMBIGUOUS


class LegacyScope(NamedTuple):
    """One stored entry the ratified grammar refuses. The third scope form.

    Four fields on purpose: the readable forms carry two, so no ``set(a) & set(b)``
    can collide a legacy entry with an ``ExactFile`` under tuple equality --
    the same trap the readable forms answer with their ``kind`` discriminator.
    """

    #: Exactly the stored text. Never stripped, re-slashed or canonicalised:
    #: rewriting ``./pkg/b.py`` to ``pkg/b.py`` would make the record's
    #: ``scope_digest`` disagree with the scope its producer wrote.
    raw: str
    generation: ScopeGeneration
    interpretation: ScopeInterpretation
    #: The typed reason today's door gives for refusing it.
    refusal_reason: str


#: Everything a persisted scope can hold. Strictly wider than
#: :data:`~codeclone.contracts.scope_grammar.AllowedScopeEntry`, which stays
#: two-membered because only those two forms may authorise a write.
StoredScopeEntry: TypeAlias = AllowedScopeEntry | LegacyScope

#: Weakest first: a scope's reading is only as settled as its least settled
#: entry, so a record answers with the interpretation that says the least.
_INTERPRETATION_STRENGTH: Final[tuple[ScopeInterpretation, ...]] = (
    ScopeInterpretation.AMBIGUOUS,
    ScopeInterpretation.PRODUCER_SPECIFIC,
    ScopeInterpretation.KNOWN,
)

#: Strongest first. A positive fact from one entry settles a scope its
#: neighbour cannot answer for; an unknown outranks a negative, because
#: "nothing covered it" is only true when nothing *could* have.
_RELATION_STRENGTH: Final[tuple[ScopeRelation, ...]] = (
    ScopeRelation.INSIDE,
    ScopeRelation.LEGACY_AMBIGUOUS,
    ScopeRelation.OUTSIDE,
)

_AMBIGUOUS_NEXT_STEP: Final = (
    "read this entry as the raw text it stores; it predates the allowed_files "
    "grammar and no current-grammar reading of it is evidence of what it "
    "authorised. To decide a new write, declare a new scope."
)

_KNOWN_NEXT_STEP: Final = (
    "read this entry as the raw text it stores; it names nothing, so every "
    "reading of it excluded every path and the audit answers without "
    "re-reading it under today's grammar."
)

_RECORD_LEGACY_NEXT_STEP: Final = (
    "this record's scope holds an entry written before the allowed_files "
    "grammar; report it verbatim and do not derive an in-scope or out-of-scope "
    "verdict from it. Closed intents never authorise a write again, so there "
    "is nothing to migrate."
)


def _producer_next_step(interpreter: str) -> str:
    return (
        f"this entry's reading is recorded as {interpreter}'s; recover it from "
        f"that consumer's history rather than re-deriving one under today's "
        "grammar, and report the raw text either way."
    )


def _pre_grammar_normalise(text: str) -> str | None:
    """The pre-grammar declaration door, re-derived from its frozen source.

    ``a7385bfc^:codeclone/surfaces/mcp/_intent.py::_normalize_path``: it
    slashed backslashes, stripped, mapped ``"."`` to ``""``, dropped a leading
    ``"./"``, right-stripped ``"/"``, and refused absolute and traversing
    paths. ``None`` stands for that refusal.
    """

    value = str(text).replace("\\", "/").strip()
    if value == ".":
        return ""
    if value.startswith("./"):
        value = value[2:]
    value = value.rstrip("/")
    if Path(value).is_absolute() or ".." in Path(value).parts:
        return None
    return value


def _pre_grammar_door_emits(raw: str) -> bool:
    """Whether some declared input reached the registry spelled exactly ``raw``.

    A stored text is in the old door's image when the door maps it to itself,
    because then the declaration that produced it was the text itself. ``""``
    is the one text with a different pre-image: the door wrote it for a scope
    declared as ``"."``, and its own list filter dropped anything that stripped
    to nothing, so ``""`` could not have been declared literally.
    """

    if raw == "":
        return _pre_grammar_normalise(".") == ""
    return bool(raw.strip()) and _pre_grammar_normalise(raw) == raw


def _stored_interpretation(
    *,
    settled: bool,
    interpreter: str | None,
) -> ScopeInterpretation:
    """The closed tri-state, from the two facts that decide it.

    ``settled`` is a measured property of the form, never of the record:
    an exact file is the one live form the three pre-grammar predicates read
    alike, and an entry that names nothing covered no path under any of them.
    """

    if settled:
        return ScopeInterpretation.KNOWN
    if interpreter is not None:
        return ScopeInterpretation.PRODUCER_SPECIFIC
    return ScopeInterpretation.AMBIGUOUS


def read_stored_scope_entry(
    text: str,
    *,
    interpreter: str | None = None,
) -> StoredScopeEntry:
    """Read one persisted entry into the full IR. Total: it refuses nothing."""

    raw = str(text)
    try:
        return parse_scope_entry(raw)
    except ScopeGrammarError as refusal:
        return LegacyScope(
            raw=raw,
            generation=(
                ScopeGeneration.PRE_GRAMMAR
                if _pre_grammar_door_emits(raw)
                else ScopeGeneration.NO_DECLARATION_DOOR
            ),
            interpretation=_stored_interpretation(
                settled=refusal.reason == SCOPE_ENTRY_EMPTY,
                interpreter=interpreter,
            ),
            refusal_reason=refusal.reason,
        )


class AuditScopeEntry(NamedTuple):
    """One persisted scope entry, read without being re-decided."""

    #: The stored text, byte for byte.
    raw: str
    status: str
    kind: str | None
    refusal_reason: str | None
    historical_reading: str
    interpreter: str | None
    next_step: str | None
    generation: ScopeGeneration | None
    interpretation: ScopeInterpretation
    form: StoredScopeEntry

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
            "generation": None if self.generation is None else self.generation.value,
            "interpretation": self.interpretation.value,
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


def _next_step_for(
    interpretation: ScopeInterpretation,
    interpreter: str | None,
) -> str:
    if interpretation is ScopeInterpretation.KNOWN:
        return _KNOWN_NEXT_STEP
    if interpretation is ScopeInterpretation.PRODUCER_SPECIFIC:
        return _producer_next_step(str(interpreter))
    return _AMBIGUOUS_NEXT_STEP


def read_audit_scope_entry(
    text: str,
    *,
    interpreter: str | None = None,
) -> AuditScopeEntry:
    """Read one persisted entry for audit. Total: it refuses nothing."""

    form = read_stored_scope_entry(text, interpreter=interpreter)
    if isinstance(form, LegacyScope):
        return AuditScopeEntry(
            raw=form.raw,
            status=LEGACY_AMBIGUOUS,
            kind=None,
            refusal_reason=form.refusal_reason,
            historical_reading=_historical_reading(form.interpretation),
            interpreter=interpreter,
            next_step=_next_step_for(form.interpretation, interpreter),
            generation=form.generation,
            interpretation=form.interpretation,
            form=form,
        )
    interpretation = _stored_interpretation(
        settled=isinstance(form, ExactFile),
        interpreter=interpreter,
    )
    return AuditScopeEntry(
        raw=str(text),
        status=CURRENT_GRAMMAR,
        kind=form.kind.value,
        refusal_reason=None,
        historical_reading=_historical_reading(interpretation),
        interpreter=interpreter,
        next_step=None,
        generation=None,
        interpretation=interpretation,
        form=form,
    )


def _historical_reading(interpretation: ScopeInterpretation) -> str:
    """The two-valued field this tri-state refines, kept for its readers."""

    if interpretation is ScopeInterpretation.KNOWN:
        return HISTORICAL_UNAMBIGUOUS
    return HISTORICAL_PRODUCER_SPECIFIC


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


def _legacy_scope_relation(entry: LegacyScope, path: str) -> ScopeRelation:
    """Relation of one unreadable entry to one path.

    Two outcomes, never three. A positive claim derived from an entry this
    grammar cannot read would be exactly the verdict the ruling forbids, so
    ``INSIDE`` is not written here at all: no input, and no future edit to the
    envelopes below, can produce one.

    The envelope is the generation's:

    ``PRE_GRAMMAR``
        the text was a live scope entry, read by consumers measured to
        disagree, so the refusal covers everything under its literal head;
    ``NO_DECLARATION_DOOR``
        no consumer ever read it, so the only reading it had is its own text.
    """

    if entry.interpretation is ScopeInterpretation.KNOWN:
        # It named nothing. Every reading excluded every path, and that is a
        # measured agreement rather than an absence of evidence.
        return ScopeRelation.OUTSIDE
    if entry.generation is ScopeGeneration.PRE_GRAMMAR:
        refused = path.startswith(_literal_head(entry.raw))
    else:
        refused = path == entry.raw.replace("\\", "/").strip()
    return ScopeRelation.LEGACY_AMBIGUOUS if refused else ScopeRelation.OUTSIDE


def _entry_relation(entry: AuditScopeEntry, path: str) -> ScopeRelation:
    """Relation of one entry to one path. Total over the closed entry forms."""

    form = entry.form
    if isinstance(form, LegacyScope):
        return _legacy_scope_relation(form, path)
    if not entry_contains_path(form, path):
        # Outside the entry every reading agreed, prefix and glob included.
        return ScopeRelation.OUTSIDE
    # Inside it they did not. Only the form they all read alike still answers,
    # which is why ``interpretation`` decides here instead of being a field the
    # payload reports and nothing consults.
    if entry.interpretation is ScopeInterpretation.KNOWN:
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


def _weakest_interpretation(
    entries: Sequence[AuditScopeEntry],
) -> ScopeInterpretation:
    """The least settled reading among ``entries``, which must not be empty.

    No default: the only caller holds the legacy entries it already counted, so
    a fallback here would be a branch no input can reach.
    """

    return min(
        (entry.interpretation for entry in entries),
        key=_INTERPRETATION_STRENGTH.index,
    )


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
        weakest = _weakest_interpretation(legacy)
        payload["interpretation"] = weakest.value
        payload["historical_interpretation"] = _historical_reading(weakest)
        payload["refusal_reasons"] = sorted(
            {str(entry.refusal_reason) for entry in legacy}
        )
        payload["next_step"] = (
            _RECORD_LEGACY_NEXT_STEP
            if weakest is ScopeInterpretation.AMBIGUOUS
            else _next_step_for(weakest, interpreter)
        )
    return payload


__all__ = [
    "CURRENT_GRAMMAR",
    "HISTORICAL_PRODUCER_SPECIFIC",
    "HISTORICAL_UNAMBIGUOUS",
    "LEGACY_AMBIGUOUS",
    "LEGACY_RELATION_FUNCTION",
    "SCOPE_INTERPRETER_FIELD",
    "AuditScopeEntry",
    "LegacyScope",
    "ScopeGeneration",
    "ScopeInterpretation",
    "ScopeRelation",
    "StoredScopeEntry",
    "audit_scope_payload",
    "audit_scope_relation",
    "read_audit_scope",
    "read_audit_scope_entry",
    "read_stored_scope_entry",
    "scope_interpreter_from_record",
]
