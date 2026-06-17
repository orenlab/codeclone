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

# Everything after the first WHERE — the predicate columns live here.
_WHERE_RE = re.compile(r"\bwhere\b(.*)")
# An identifier immediately left of a comparison operator — a filter column.
_WHERE_COLUMN_RE = re.compile(
    r"([a-z_][a-z0-9_$.]*)\s*(?:<=|>=|!=|<>|=|<|>|\bin\b|\bis\b|\blike\b)"
)
# The projection list between SELECT and FROM (count(*) / distinct x / columns).
_PROJECTION_RE = re.compile(r"^select\s+(.*?)\s+from\b")
_MAX_WHERE_COLUMNS = 4


@dataclass(frozen=True, slots=True)
class SqlFingerprint:
    """Normalized shape of one SQL statement (literal-free)."""

    fingerprint: str
    table_hint: str | None
    kind: str  # select | insert | update | delete | other


@dataclass(frozen=True, slots=True)
class SqlShape:
    """Human-facing interpretation of a fingerprint for the cockpit.

    ``summary`` reads like "count by repo_root_digest, workflow_id" or
    "by memory_id" — the predicate, not the raw SQL, so a query count decodes
    into *what it filters on*.
    """

    kind: str
    table: str | None
    where_columns: tuple[str, ...]
    summary: str


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


def _where_columns(normalized: str) -> tuple[str, ...]:
    match = _WHERE_RE.search(normalized)
    if not match:
        return ()
    seen: list[str] = []
    for raw in _WHERE_COLUMN_RE.findall(match.group(1)):
        # Strip a table/alias prefix (t.id -> id); keep first-seen order.
        column = raw.split(".")[-1]
        if column not in seen:
            seen.append(column)
    return tuple(seen)


def _projection(normalized: str) -> str | None:
    match = _PROJECTION_RE.match(normalized)
    if not match:
        return None
    columns = match.group(1).strip()
    if columns.startswith("count("):
        return "count"
    if columns.startswith("distinct "):
        target = columns[len("distinct ") :].split(",", 1)[0].strip()
        return f"distinct {target}"
    return None


def _summarize(kind: str, normalized: str, where_columns: tuple[str, ...]) -> str:
    shown = ", ".join(where_columns[:_MAX_WHERE_COLUMNS])
    if len(where_columns) > _MAX_WHERE_COLUMNS:
        shown += ", …"
    head = _projection(normalized) or ""
    if shown and head:
        return f"{head} by {shown}"
    if shown:
        return f"by {shown}"
    if head:
        return head
    return "all rows" if kind == "select" else ""


def describe_fingerprint(fingerprint: str) -> SqlShape:
    """Interpret a (normalized or raw) statement into a cockpit-facing shape:
    its kind, table, predicate columns, and a one-line ``summary``.
    """
    fp = fingerprint_sql(fingerprint)
    where_columns = _where_columns(fp.fingerprint)
    return SqlShape(
        kind=fp.kind,
        table=fp.table_hint,
        where_columns=where_columns,
        summary=_summarize(fp.kind, fp.fingerprint, where_columns),
    )


__all__ = ["SqlFingerprint", "SqlShape", "describe_fingerprint", "fingerprint_sql"]
