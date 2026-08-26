# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Generic, TypeVar

from ...budget.estimator import (
    TOKEN_ESTIMATOR_CHARS_APPROX,
    TOKEN_ESTIMATOR_TIKTOKEN,
    TokenEstimatorMode,
    canonical_payload_json,
    estimate_payload,
)
from ...observability import payload_token_estimator
from ._context_governance import (
    CONTEXT_GOVERNANCE_CONTRACT_VERSION,
    CONTEXT_GOVERNANCE_ESTIMATOR,
)

T = TypeVar("T")


def measure_payload(payload: Mapping[str, object]) -> tuple[int, int]:
    """Return ``(byte_size, context_unit_estimate)`` for canonical JSON.

    Both numbers describe the same canonical text: ``byte_size`` is its UTF-8
    length, and the context units are counted over that same text by the shared
    estimator in the mode this process was configured with — or taken from a
    valid ``context_governance`` envelope, which declares its own estimator.
    Never raises: payload measurement must never break the tool call it wraps.
    """
    text = _canonical_payload_text(payload)
    if text is None:
        return 0, 0
    byte_size = len(text.encode("utf-8"))
    return byte_size, _payload_context_units(payload, text)


def _canonical_payload_text(payload: Mapping[str, object]) -> str | None:
    try:
        return canonical_payload_json(payload)
    except (TypeError, ValueError):
        return None


def _configured_estimator() -> TokenEstimatorMode:
    """Narrow the process-wide configured mode to the estimator's vocabulary.

    The observability config carries the mode as a plain string because the
    model store may only reach the contract ring. Anything other than the exact
    mode resolves to the approximation here, so an unrecognised value can never
    reach the estimator as an error, and never as a claim of exactness.
    """
    if payload_token_estimator() == TOKEN_ESTIMATOR_TIKTOKEN:
        return TOKEN_ESTIMATOR_TIKTOKEN
    return TOKEN_ESTIMATOR_CHARS_APPROX


def _payload_context_units(payload: Mapping[str, object], text: str) -> int:
    governed_estimate = _context_governance_estimate(payload)
    if governed_estimate is not None:
        return governed_estimate
    try:
        return estimate_payload(payload, estimator=_configured_estimator()).tokens
    except Exception:
        # Deliberately wider than the estimator's own typed failures. The exact
        # mode reaches for a BPE table on first use, so this call can now fail
        # in ways the approximation never could, and this measurement wraps
        # every MCP tool call. The instrument degrades to the approximation
        # rather than taking the tool down with it.
        return ceil(len(text) / 4)


def _context_governance_estimate(payload: Mapping[str, object]) -> int | None:
    governance = payload.get("context_governance")
    if not isinstance(governance, Mapping):
        return None
    if governance.get("contract_version") != CONTEXT_GOVERNANCE_CONTRACT_VERSION:
        return None
    if governance.get("estimator") != CONTEXT_GOVERNANCE_ESTIMATOR:
        return None
    estimated = governance.get("estimated")
    if type(estimated) is not int or estimated < 0:
        return None
    return estimated


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
