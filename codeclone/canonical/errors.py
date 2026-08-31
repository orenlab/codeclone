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


class UnknownRunError(RunStoreError):
    """The requested ``run_id`` is not a published run of this store."""


class ExportIntegrityError(RunStoreError):
    """Exported artifact bytes disagree with their export envelope.

    Raised by envelope verification when the artifact digest, the declared
    byte count, or the declared wire revision does not prove against the
    bytes at hand.  The artifact digest is projection-layer identity — it
    covers the wire revision, which ``run_id`` never does (brief §5).
    """
