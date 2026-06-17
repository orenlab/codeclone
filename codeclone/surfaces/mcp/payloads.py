# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Generic, TypeVar

from ...budget.estimator import estimate_payload

T = TypeVar("T")


def measure_payload(payload: Mapping[str, object]) -> tuple[int, int]:
    """Return ``(byte_size, token_estimate)`` for a payload's canonical JSON.

    ``byte_size`` is the UTF-8 length of the canonical JSON; tokens reuse the
    shared budget estimator (chars-approx default — no ``tiktoken`` import). Never
    raises: payload measurement must never break the tool call it wraps.
    """
    try:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return 0, 0
    byte_size = len(text.encode("utf-8"))
    try:
        tokens = estimate_payload(payload).tokens
    except (TypeError, ValueError):
        tokens = ceil(len(text) / 4)
    return byte_size, tokens


@dataclass(frozen=True, slots=True)
class PageWindow(Generic[T]):
    items: list[T]
    offset: int
    limit: int
    total: int
    next_offset: int | None


def paginate(
    items: Sequence[T],
    *,
    offset: int,
    limit: int,
    max_limit: int,
) -> PageWindow[T]:
    normalized_offset = max(0, offset)
    normalized_limit = max(1, min(limit, max_limit))
    page = list(items[normalized_offset : normalized_offset + normalized_limit])
    next_offset = normalized_offset + len(page)
    return PageWindow(
        items=page,
        offset=normalized_offset,
        limit=normalized_limit,
        total=len(items),
        next_offset=(next_offset if next_offset < len(items) else None),
    )


def resolve_finding_id(
    *,
    canonical_to_short: Mapping[str, str],
    short_to_canonical: Mapping[str, str],
    finding_id: str,
) -> str | None:
    if finding_id in canonical_to_short:
        return finding_id
    return short_to_canonical.get(finding_id)


def short_id(value: str, *, length: int = 8) -> str:
    return value[:length]
