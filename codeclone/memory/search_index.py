# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from .models import MemoryRecord, MemorySubject

SearchMatchMode = Literal["all", "any"]

_FTS_TOKEN_RE = re.compile(r"[^\w./-]+", re.UNICODE)


def build_search_text(
    *,
    record: MemoryRecord,
    subjects: Sequence[MemorySubject],
) -> str:
    parts: list[str] = [
        record.statement,
        record.summary or "",
        record.type,
        record.ingest_source,
    ]
    for subject in subjects:
        parts.append(subject.subject_kind)
        parts.append(subject.subject_key.replace("\\", "/"))
    if record.payload:
        parts.append(_payload_search_text(record.payload))
    return " ".join(part.strip() for part in parts if part and part.strip())


def _payload_search_text(payload: object) -> str:
    if isinstance(payload, dict):
        tokens: list[str] = []
        for key, value in sorted(payload.items()):
            tokens.append(str(key))
            if isinstance(value, str):
                tokens.append(value)
            elif isinstance(value, list):
                tokens.extend(str(item) for item in value)
        return " ".join(tokens)
    return str(payload)


def tokenize_query(query: str) -> tuple[str, ...]:
    normalized = query.replace("\\", "/").strip()
    if not normalized:
        return ()
    raw_tokens = _FTS_TOKEN_RE.split(normalized.lower())
    seen: list[str] = []
    for token in raw_tokens:
        text = token.strip(".")
        if len(text) < 2:
            continue
        if text not in seen:
            seen.append(text)
    return tuple(seen)


def fts_match_expression(
    query: str,
    *,
    match_mode: SearchMatchMode = "any",
) -> str | None:
    tokens = tokenize_query(query)
    if not tokens:
        return None
    escaped = [_escape_fts_token(token) for token in tokens]
    joiner = " AND " if match_mode == "all" else " OR "
    return joiner.join(escaped)


def _escape_fts_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def like_match_expression(
    query: str,
    *,
    match_mode: SearchMatchMode = "any",
) -> tuple[list[str], list[str]]:
    """Return SQL LIKE clauses and params for fallback search."""
    tokens = tokenize_query(query)
    if not tokens:
        return [], []
    clauses: list[str] = []
    params: list[str] = []
    for token in tokens:
        clauses.append("LOWER(search_blob) LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(token.lower())}%")
    if match_mode == "all":
        return ["(" + " AND ".join(clauses) + ")"], params
    return ["(" + " OR ".join(clauses) + ")"], params


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = [
    "SearchMatchMode",
    "build_search_text",
    "fts_match_expression",
    "like_match_expression",
    "tokenize_query",
]
