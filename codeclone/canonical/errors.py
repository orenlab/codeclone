# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Typed failures of the canonical model (F-3) and its wire codec.

Two distinct failure surfaces, never conflated:

* :class:`CanonicalModelError` — producer-side: a value violates a model law
  before it ever reaches the wire (path grammar, closed vocabularies,
  duplicate logical keys).
* :class:`WireDecodeError` — decoder-side: a typed refusal with a stable
  ``W``-code from the closed refusal table of the wire contract (F-3 §7.7).
  One error class carries one code; silent degradation is forbidden.
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
