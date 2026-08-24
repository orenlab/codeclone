# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Export envelope of the canonical run-store — backend wave 3.

``run != report artifact`` (brief §5): a run is semantic state; an exported
canonical document is one *projection* of that state under one wire
revision.  The two identities are deliberately different:

* ``run_id`` hashes the analysis layers, scope, and membership — the
  projection layer never reaches back into it (brief §5: a report revision
  must not change the identity of a semantic run);
* the **artifact digest** seals the concrete exported bytes under a domain
  that carries the wire revision — the same run projected under two wire
  revisions is one run and two artifacts.

The envelope also carries the store's layered compatibility witness (brief
§4.1) verbatim, so a consumer holding only bytes plus envelope can name the
generation that produced them.  The document's own ``integrity`` member
(inner seal, codec domain) proves the body against itself; the artifact
digest (outer seal, this module) proves the whole byte stream against the
envelope — including the integrity tail the inner seal cannot cover.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Protocol

from codeclone.canonical.errors import ExportIntegrityError
from codeclone.contracts import CANONICAL_WIRE_REVISION

_ARTIFACT_DOMAIN_PREFIX: Final = "cc-canonical-artifact:"


class ByteSink(Protocol):
    """Anything an export can stream canonical bytes into."""

    def write(self, data: bytes, /) -> object:
        """Consume one chunk of the canonical byte stream."""


def artifact_domain(wire_revision: str = CANONICAL_WIRE_REVISION) -> bytes:
    """Domain-separation prefix of the artifact digest.

    The wire revision lives INSIDE this domain and stays OUT of ``run_id``
    (brief §5).  One owner: the store's streaming exporter seeds its hasher
    here, and :func:`canonical_artifact_digest` recomputes through the same
    bytes — there is no second spelling of the preimage.
    """
    return f"{_ARTIFACT_DOMAIN_PREFIX}{wire_revision}\x00".encode()


def canonical_artifact_digest(
    data: bytes, *, wire_revision: str = CANONICAL_WIRE_REVISION
) -> str:
    """The artifact digest of one exported canonical document."""
    return hashlib.sha256(artifact_domain(wire_revision) + data).hexdigest()


@dataclass(frozen=True, slots=True)
class WitnessLayer:
    """One layer of the store's compatibility witness, as stored."""

    layer: str
    revision: str
    role: str


@dataclass(frozen=True, slots=True)
class ExportEnvelope:
    """Receipt of one canonical export.

    ``run_id`` names the semantic run (projection-free); ``artifact_digest``
    names these bytes under this ``wire_revision``; ``witness`` is the
    store's layered generation, read from the store — not restated from
    process constants.
    """

    run_id: str
    artifact_digest: str
    byte_count: int
    wire_revision: str
    witness: tuple[WitnessLayer, ...]


def verify_export_artifact(data: bytes, envelope: ExportEnvelope) -> None:
    """Prove exported bytes against their envelope; typed refusals only.

    A refusal names the first disagreement — declared wire revision this
    process cannot verify, byte count, or artifact digest.  Corruption of a
    single byte anywhere in the stream, integrity tail included, is loud.
    """
    if envelope.wire_revision != CANONICAL_WIRE_REVISION:
        raise ExportIntegrityError(
            f"envelope declares wire revision {envelope.wire_revision!r}; "
            f"this process verifies revision {CANONICAL_WIRE_REVISION!r} only"
        )
    if len(data) != envelope.byte_count:
        raise ExportIntegrityError(
            f"artifact is {len(data)} bytes; the envelope declares "
            f"{envelope.byte_count}"
        )
    recomputed = canonical_artifact_digest(data, wire_revision=envelope.wire_revision)
    if recomputed != envelope.artifact_digest:
        raise ExportIntegrityError(
            "artifact bytes do not hash to the envelope digest (declared "
            f"{envelope.artifact_digest[:12]}…, recomputed {recomputed[:12]}…)"
        )


__all__ = [
    "ByteSink",
    "ExportEnvelope",
    "WitnessLayer",
    "artifact_domain",
    "canonical_artifact_digest",
    "verify_export_artifact",
]
