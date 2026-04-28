# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


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
