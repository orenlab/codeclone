# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic token-count estimator for MCP JSON payloads.

Defaults to ``ceil(chars / 4)`` so long-lived MCP processes do not import
``tiktoken`` just because the optional package is installed. Exact BPE
counting remains available through explicit ``estimator="tiktoken"`` opt-in.

The payload is serialized to canonical JSON (sorted keys, compact separators,
no ASCII escaping) before counting.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

TokenEstimatorMode = Literal["chars_approx", "tiktoken"]

TOKEN_ESTIMATOR_CHARS_APPROX: Final[TokenEstimatorMode] = "chars_approx"
TOKEN_ESTIMATOR_TIKTOKEN: Final[TokenEstimatorMode] = "tiktoken"
TOKEN_ESTIMATOR_MODES: Final[frozenset[str]] = frozenset(
    {TOKEN_ESTIMATOR_CHARS_APPROX, TOKEN_ESTIMATOR_TIKTOKEN}
)


@dataclass(frozen=True, slots=True)
class TokenEstimate:
    """Result of a payload token estimation."""

    encoding: str  # e.g. "o200k_base" or "chars_approx"
    characters: int
    tokens: int
    method: str  # "tiktoken" | "chars_approx"


def estimate_payload(
    payload: Mapping[str, object],
    *,
    encoding: str = "o200k_base",
    estimator: TokenEstimatorMode = TOKEN_ESTIMATOR_CHARS_APPROX,
) -> TokenEstimate:
    """Estimate token count for a canonical JSON payload.

    Character approximation is the default because this function is used by
    long-lived MCP audit paths. ``tiktoken`` is imported only when explicitly
    requested. If exact estimation is requested but unavailable, the function
    falls back to approximation without failing audit writes.
    """
    text = _canonical_json(payload)
    characters = len(text)
    if estimator not in TOKEN_ESTIMATOR_MODES:
        expected = ", ".join(sorted(TOKEN_ESTIMATOR_MODES))
        raise ValueError(f"token estimator must be one of: {expected}")
    if estimator == TOKEN_ESTIMATOR_TIKTOKEN:
        return _tiktoken_or_chars_estimate(
            text,
            encoding=encoding,
            characters=characters,
        )
    return _chars_approx_estimate(characters)


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


class _TiktokenUnavailable(Exception):
    pass


def _tiktoken_estimate(text: str, *, encoding: str) -> TokenEstimate:
    try:
        import tiktoken
    except ImportError as exc:
        raise _TiktokenUnavailable from exc
    enc = tiktoken.get_encoding(encoding)
    tokens = len(enc.encode(text))
    return TokenEstimate(
        encoding=encoding,
        characters=len(text),
        tokens=tokens,
        method="tiktoken",
    )


def _tiktoken_or_chars_estimate(
    text: str,
    *,
    encoding: str,
    characters: int,
) -> TokenEstimate:
    try:
        return _tiktoken_estimate(text, encoding=encoding)
    except _TiktokenUnavailable:
        return _chars_approx_estimate(characters)


def _chars_approx_estimate(characters: int) -> TokenEstimate:
    return TokenEstimate(
        encoding=TOKEN_ESTIMATOR_CHARS_APPROX,
        characters=characters,
        tokens=_approx_tokens(characters),
        method=TOKEN_ESTIMATOR_CHARS_APPROX,
    )


def _approx_tokens(characters: int) -> int:
    """Rough approximation: 1 token ~ 4 characters for JSON."""
    return -(-characters // 4)  # ceil division


__all__ = [
    "TOKEN_ESTIMATOR_CHARS_APPROX",
    "TOKEN_ESTIMATOR_MODES",
    "TOKEN_ESTIMATOR_TIKTOKEN",
    "TokenEstimate",
    "TokenEstimatorMode",
    "estimate_payload",
]
