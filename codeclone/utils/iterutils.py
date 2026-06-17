# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Small iterator utilities shared across the package."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypeVar

_T = TypeVar("_T")


def chunked(items: Iterable[_T], size: int) -> Iterator[tuple[_T, ...]]:
    """Yield successive ``size``-length tuples from ``items``; the final chunk
    may be shorter. Empty input yields nothing.

    Python 3.10+ compatible (stdlib ``itertools.batched`` is 3.12+).
    """
    if size < 1:
        msg = "size must be >= 1"
        raise ValueError(msg)
    iterator = iter(items)
    while chunk := tuple(islice(iterator, size)):
        yield chunk


__all__ = ["chunked"]
