# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Typed failures of the canonical model (F-3), its wire codec, and the
run-store.

Distinct failure surfaces, never conflated:

* :class:`CanonicalModelError` — producer-side: a value violates a model law
  before it ever reaches the wire (closed vocabularies, duplicate logical
  keys).  :class:`SemanticGrammarError` narrows it for the shared identity
  grammar, and :class:`LegacyIngestError` narrows THAT for the document
  shape only the legacy ingest oracle can be handed.
* :class:`WireDecodeError` — decoder-side: a typed refusal with a stable
  ``W``-code from the closed refusal table of the wire contract (F-3 §7.7).
  One error class carries one code; silent degradation is forbidden.
* :class:`RunStoreError` and its narrowings — storage-side: compatibility
  refusal at open (law 7), per-mutation fencing (brief §4.2), content
  integrity on read, and unknown-run lookups.
"""

from __future__ import annotations

from typing import Final


class CanonicalModelError(ValueError):
    """A value violates a canonical-model law on the producer side."""


class WireDecodeError(ValueError):
    """Typed decoder refusal carrying a stable wire-contract code.

    ``code`` is one of the ``W``-codes from the closed refusal table.
    ``W11`` was deleted by maintainer sanction (2026-08-13) and is never
    raised nor reused.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class SemanticGrammarError(CanonicalModelError):
    """The canonical identity grammar refuses a producer spelling.

    The ONE typed result of ``codeclone.canonical.semantic_grammar``, shared
    by every consumer of the grammar (2026-08-31 authority transplant).  It
    is deliberately not per-consumer: before the transplant the legacy
    ingest oracle and a producer-native path would each have refused in
    their own dialect, which is the second law the transplant removes.
    Refusal is always fail-closed — a spelling that does not resolve names
    no entity, and a guessed identity would silently become a wrong content
    address in the run store.
    """


class LegacyIngestError(SemanticGrammarError):
    """The legacy producer document cannot be ingested honestly.

    Narrows the grammar refusal to the document-SHAPE failures only the
    ingest oracle can have (a missing key, a value that is not an object or
    an array).  Identity-grammar refusals now come from the shared owner as
    :class:`SemanticGrammarError` itself; this subclass keeps the two
    distinguishable, and keeps every existing ``LegacyIngestError`` handler
    catching what it always caught.
    """


class RunStoreError(RuntimeError):
    """Base typed failure of the canonical run-store (backend wave 2)."""


class StoreCompatibilityError(RunStoreError):
    """Law 7 refusal at ``open``: the store's layered compatibility witness
    is not the one this process declares.  The process refuses the stored
    generation; it never guesses."""


class StoreFenceError(RunStoreError):
    """Per-mutation fencing refusal (brief §4.2): the store generation
    (epoch, storage schema, contract epoch) moved under an open handle, so
    the mutating transaction is refused — compatibility at ``open`` alone
    would let a stale process write through the back door."""


class StoreIntegrityError(RunStoreError):
    """Stored bytes disagree with their own content address or digests.

    Raised on read when an object's payload no longer hashes to its
    ``object_id`` or a run's membership/identity digests do not recompute.
    Corruption is loud, never a silently different projection.
    """


#: Machine-readable reasons a run lookup cannot be answered.  Stable
#: tokens: a caller may branch on them, so a rename is a contract change.
UNKNOWN_RUN_STORE_ABSENT: Final = "run_store_absent"
UNKNOWN_RUN_NOT_PUBLISHED: Final = "run_not_published"
UNKNOWN_RUN_NOT_OF_STORE: Final = "run_not_of_store"
UNKNOWN_RUN_HEAD_ABSENT: Final = "target_head_absent"

#: One executable remediation per reason.  Closed on purpose: the lookup is
#: a plain subscript, so a raise site that invents a reason fails at the
#: raise instead of shipping a typed outcome with nothing to act on.
_UNKNOWN_RUN_NEXT_STEP: Final[dict[str, str]] = {
    UNKNOWN_RUN_STORE_ABSENT: (
        "point the read at the store this workspace publishes to "
        "(.codeclone/db/runs.sqlite3 under the repository root), or run an "
        "analysis with the run store enabled so that a store exists to read"
    ),
    UNKNOWN_RUN_NOT_PUBLISHED: (
        "resolve the run through head(namespace=..., target=...) and read the "
        "run_id it names, or publish this model with write_full_run before "
        "reading it back"
    ),
    UNKNOWN_RUN_NOT_OF_STORE: (
        "address the store that holds this run, or publish the run into this "
        "store with write_full_run before retaining or releasing it"
    ),
    UNKNOWN_RUN_HEAD_ABSENT: (
        "publish a run for this target with write_full_run before exporting "
        "its head, or export a known run directly with export_run(store, "
        "run_id, sink)"
    ),
}


class UnknownRunError(RunStoreError):
    """A run lookup this store cannot answer.

    Covers the absent store as well as the absent run: a path that holds no
    store publishes no runs, and a reader must be told so without the store
    being brought into existence to say it.

    Carries the machine-readable ``reason`` and an executable ``next_step``,
    the shape :class:`~codeclone.contracts.scope_grammar.ScopeGrammarError`
    already set for a typed refusal an agent has to act on rather than parse.
    ``reason`` is required and its remediation is a plain subscript of the
    closed table: a refusal with nothing to do next is not shippable, so it
    is not constructible either.
    """

    __slots__ = ("next_step", "reason")

    def __init__(self, detail: str, *, reason: str) -> None:
        next_step = _UNKNOWN_RUN_NEXT_STEP[reason]
        super().__init__(f"{detail} (reason: {reason}). next_step: {next_step}.")
        self.reason = reason
        self.next_step = next_step


class RunReportLinkError(RunStoreError):
    """The identity bridge cannot be stated, or cannot be trusted.

    The persisted edge relates one immutable analysis row to one evaluated
    report identity, and the scope receipt proves the two are compatible.
    Every way that relation can go wrong refuses here rather than degrading:
    a pair whose halves describe different analyzed scopes, an edge to a row
    the store does not hold, and an index that offers two analyses for one
    evaluation.  Refusing is the point, because a wrong edge is invisible at
    both endpoints -- the store run verifies against its own membership and
    the document against its own integrity block, so only the relation is
    false and only this owner looks at the relation.
    """


class ExportIntegrityError(RunStoreError):
    """Exported artifact bytes disagree with their export envelope.

    Raised by envelope verification when the artifact digest, the declared
    byte count, or the declared wire revision does not prove against the
    bytes at hand.  The artifact digest is projection-layer identity — it
    covers the wire revision, which ``run_id`` never does (brief §5).
    """
