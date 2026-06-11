# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""SQL statement fingerprinting for DB observability (Phase 29.DB, Track B).

Performance-truth only: reduce a SQL statement to its normalized *shape* so the
cockpit can turn "1892 queries" into "1200x SELECT evidence by trajectory_id".
The fingerprint is literal-free by construction — every string/number value is
replaced with ``?`` — so it is safe to persist without leaking row data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Bound the persisted shape; pathological statements must not bloat the column.
_MAX_FINGERPRINT_CHARS = 200

_WHITESPACE_RE = re.compile(r"\s+")
# Single-quoted string literal with doubled-quote ('') escapes; unrolled so it
# stays linear-time (no nested quantifier to backtrack on).
_STRING_RE = re.compile(r"'[^']*(?:''[^']*)*'")
_HEX_RE = re.compile(r"\b0x[0-9a-f]+\b")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
# ``( ?, ?, ? )`` / ``( ? )`` -> ``(?)`` so IN/VALUES arity does not fan out
# distinct shapes for the same statement.
_PLACEHOLDER_LIST_RE = re.compile(r"\(\s*\?(?:\s*,\s*\?)*\s*\)")
# First identifier after a table-introducing keyword.
_TABLE_HINT_RE = re.compile(r"\b(?:from|into|update|join)\s+([a-z_][a-z0-9_$]*)")

_KINDS = frozenset({"select", "insert", "update", "delete"})


@dataclass(frozen=True, slots=True)
class SqlFingerprint:
    """Normalized shape of one SQL statement (literal-free)."""

    fingerprint: str
    table_hint: str | None
    kind: str  # select | insert | update | delete | other


def _normalize(sql: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", sql.strip().lower())
    normalized = _STRING_RE.sub("?", normalized)
    normalized = _HEX_RE.sub("?", normalized)
    normalized = _NUMBER_RE.sub("?", normalized)
    normalized = _PLACEHOLDER_LIST_RE.sub("(?)", normalized)
    return normalized.strip()


def fingerprint_sql(sql: str) -> SqlFingerprint:
    """Reduce a SQL statement to its literal-free shape, table hint, and kind.

    Idempotent on its own output: fingerprinting an already-normalized statement
    returns the same shape, so a persisted fingerprint can be re-parsed for its
    table hint and kind without storing them separately.
    """
    normalized = _normalize(sql)
    if not normalized:
        return SqlFingerprint(fingerprint="", table_hint=None, kind="other")
    head = normalized.split(" ", 1)[0]
    kind = head if head in _KINDS else "other"
    table_match = _TABLE_HINT_RE.search(normalized)
    table_hint = table_match.group(1) if table_match else None
    return SqlFingerprint(
        fingerprint=normalized[:_MAX_FINGERPRINT_CHARS],
        table_hint=table_hint,
        kind=kind,
    )


__all__ = ["SqlFingerprint", "fingerprint_sql"]
