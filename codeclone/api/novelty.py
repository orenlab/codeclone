# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""R3 door: the clone novelty vocabulary, read from its owner.

The vocabulary lives with its domain owner (``codeclone.domain.findings``,
ring r2). CLI and presentation surfaces live on r4 and may not import r2
directly, so this door carries the words across the one legal path
(r4 -> r3 -> r2). Names are re-exported by assignment and the value tuple is
**derived** from the owner mechanically — no string in this module spells a
novelty word a second time, so the vocabulary keeps exactly one owner (`G2`).

A consumer that enumerates its handling per value should pin itself to
``CLONE_NOVELTY_VALUES``: when the owner grows a fourth value it flows through
this door without this file changing, and the consumer's pin fails loudly
instead of never hearing about the new word (`H1`).
"""

from __future__ import annotations

from typing import Final

from ..domain import findings as _findings

CLONE_NOVELTY_NEW: Final[str] = _findings.CLONE_NOVELTY_NEW
CLONE_NOVELTY_KNOWN: Final[str] = _findings.CLONE_NOVELTY_KNOWN
CLONE_NOVELTY_UNAVAILABLE: Final[str] = _findings.CLONE_NOVELTY_UNAVAILABLE

#: Every novelty value the owner declares, derived — never restated.
CLONE_NOVELTY_VALUES: Final[tuple[str, ...]] = tuple(
    sorted(
        value
        for name, value in vars(_findings).items()
        if name.startswith("CLONE_NOVELTY_") and isinstance(value, str)
    )
)

__all__ = [
    "CLONE_NOVELTY_KNOWN",
    "CLONE_NOVELTY_NEW",
    "CLONE_NOVELTY_UNAVAILABLE",
    "CLONE_NOVELTY_VALUES",
]
