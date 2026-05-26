# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic token-count estimator for MCP JSON payloads.

Uses ``tiktoken`` when available, falls back to ``ceil(chars / 4)``
character-based approximation otherwise.  The payload is serialized to
canonical JSON (sorted keys, compact separators, no ASCII escaping)
before counting.

This module is imported lazily by the audit writer.  Base ``codeclone``
never imports ``tiktoken``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass


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
) -> TokenEstimate:
    """Estimate token count for a canonical JSON payload.

    Uses tiktoken if available, falls back to character-based approximation.
    The payload is serialized to the same canonical form used by the audit
    writer: sorted keys, compact separators, no ASCII escaping.
    """
    text = _canonical_json(payload)
    characters = len(text)
    try:
        return _tiktoken_estimate(text, encoding=encoding)
    except _TiktokenUnavailable:
        return TokenEstimate(
            encoding="chars_approx",
            characters=characters,
            tokens=_approx_tokens(characters),
            method="chars_approx",
        )


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


def _approx_tokens(characters: int) -> int:
    """Rough approximation: 1 token ~ 4 characters for JSON."""
    return -(-characters // 4)  # ceil division


__all__ = ["TokenEstimate", "estimate_payload"]
