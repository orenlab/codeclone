# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one versioned owner of the F5 canonical signature identity.

``api_signature_identity_contract.v1`` (ruling 2026-08-24 §1, F5): the
ratified family key is ``(SYMBOL, canonical_signature_variant)`` — one
owner of the canonical signature identity, into which parameters and the
return digest enter BY CONTRACT.  The bare ``(FILE, symbol)`` key measured
10 140 of 10 143 unique on the frozen corpus: the three lost groups are
``@overload`` declarations differing only in parameters and return, so the
discriminator is the signature itself, never a guessed extra column.

Preimage (one spelling, here only): the signature version, the parameter
arity, then per parameter ``(name, kind, default marker, annotation digest
or empty)``, then the return digest or empty — ``\\x00``-joined under the
domain prefix.  The arity term keeps parameter boundaries unambiguous by
construction.  The model's key law, the wire projector, and the decoder's
recompute (W25) all call this function; none carries a second spelling.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Final, Protocol

from codeclone.contracts import API_SURFACE_SIGNATURE_VERSION

API_SIGNATURE_IDENTITY_CONTRACT: Final = "api_signature_identity_contract.v1"

_API_SIGNATURE_DOMAIN: Final = b"cc-api-signature\x00"


class SignatureParameter(Protocol):
    """What the variant reads from one parameter fact (read-only view)."""

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def has_default(self) -> bool: ...

    @property
    def annotation_digest(self) -> str | None: ...


def signature_variant(
    *, parameters: Iterable[SignatureParameter], returns_digest: str | None
) -> str:
    """The canonical signature variant of one API symbol row."""
    rows = list(parameters)
    parts: list[str] = [API_SURFACE_SIGNATURE_VERSION, str(len(rows))]
    for parameter in rows:
        parts.append(parameter.name)
        parts.append(parameter.kind)
        parts.append("1" if parameter.has_default else "0")
        parts.append(parameter.annotation_digest or "")
    parts.append(returns_digest or "")
    wire = "\x00".join(parts)
    return hashlib.sha256(_API_SIGNATURE_DOMAIN + wire.encode("utf-8")).hexdigest()
