# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Bounded, digest-bound pages over the authority discovery candidates.

Discovery proposes on the scale of a whole tree: thousands of candidates for a
repository this size. MCP therefore never serves the population, only pages of
it, under the same continuation contract the memory projection pages use --
cursor carrying the projection kind, the ordering version, the offset, the
identity digest of the population it was cut from and the digest of the request
that cut it, recomputed on every call and refused when it no longer matches.

The report document is the ordering authority: candidates arrive already ranked
by the document builder, and this module never re-sorts them.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Final

from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence

__all__ = [
    "AUTHORITY_CANDIDATE_ORDERING_VERSION",
    "AUTHORITY_CANDIDATE_PROJECTION_KIND",
    "DEFAULT_AUTHORITY_CANDIDATE_PAGE_SIZE",
    "MAX_AUTHORITY_CANDIDATE_PAGE_SIZE",
    "AuthorityCandidateCursorError",
    "authority_candidate_items",
    "authority_candidate_page",
    "bounded_authority_candidate_page_size",
]

AUTHORITY_CANDIDATE_PROJECTION_KIND: Final = "authority_candidate_projection_v1"
AUTHORITY_CANDIDATE_ORDERING_VERSION: Final = "authority_candidate_order_v1"
AUTHORITY_CANDIDATE_CURSOR_VERSION: Final = "1"
DEFAULT_AUTHORITY_CANDIDATE_PAGE_SIZE: Final = 20
MAX_AUTHORITY_CANDIDATE_PAGE_SIZE: Final = 50

_DIGEST_DOMAIN: Final = b"codeclone.mcp.authority-candidates.v1"


class AuthorityCandidateCursorError(ValueError):
    """Raised when a cursor cannot be trusted against the current run."""


def bounded_authority_candidate_page_size(value: int) -> int:
    """Clamp a requested page size into the contract's bounds."""

    if value < 1:
        return DEFAULT_AUTHORITY_CANDIDATE_PAGE_SIZE
    return min(value, MAX_AUTHORITY_CANDIDATE_PAGE_SIZE)


def authority_candidate_items(
    report_document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    """Return the candidates in the order the document builder ranked them."""

    families = _as_mapping(_as_mapping(report_document.get("metrics")).get("families"))
    authority = _as_mapping(families.get("semantic_authority"))
    return tuple(
        item
        for raw_item in _as_sequence(authority.get("items"))
        for item in (_as_mapping(raw_item),)
        if str(item.get("item_kind", "")) == "candidate"
    )


def _digest(payload: object) -> dict[str, str]:
    digest = sha256()
    digest.update(_DIGEST_DOMAIN)
    digest.update(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return {
        "kind": AUTHORITY_CANDIDATE_PROJECTION_KIND,
        "algorithm": "sha256",
        "digest_version": AUTHORITY_CANDIDATE_CURSOR_VERSION,
        "value": digest.hexdigest(),
    }


def _identity_digest(items: Sequence[Mapping[str, object]]) -> dict[str, str]:
    """Digest the population itself, so a changed run invalidates its cursors."""

    return _digest([str(item.get("candidate_id", "")) for item in items])


def _request_digest(*, run_id: str, section: str) -> dict[str, str]:
    return _digest({"run_id": run_id, "section": section})


def _encode_cursor(payload: Mapping[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_authority_candidate_cursor(cursor: str) -> Mapping[str, object]:
    """Decode a cursor, refusing anything this contract did not produce."""

    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuthorityCandidateCursorError(
            "authority candidate cursor is not decodable"
        ) from exc
    if not isinstance(payload, dict):
        raise AuthorityCandidateCursorError(
            "authority candidate cursor must decode to an object"
        )
    if payload.get("projection_kind") != AUTHORITY_CANDIDATE_PROJECTION_KIND:
        raise AuthorityCandidateCursorError(
            "authority candidate cursor belongs to another projection"
        )
    if payload.get("ordering_version") != AUTHORITY_CANDIDATE_ORDERING_VERSION:
        raise AuthorityCandidateCursorError(
            "authority candidate cursor was cut under another ordering"
        )
    return payload


def _cursor_payload(
    *,
    offset: int,
    total: int,
    identity: Mapping[str, str],
    request: Mapping[str, str],
    run_id: str,
    section: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "cursor_version": AUTHORITY_CANDIDATE_CURSOR_VERSION,
        "projection_kind": AUTHORITY_CANDIDATE_PROJECTION_KIND,
        "ordering_version": AUTHORITY_CANDIDATE_ORDERING_VERSION,
        "run_id": run_id,
        "section": section,
        "offset": offset,
        "total": total,
        "lane_identity_digest": dict(identity),
        "request_digest": dict(request),
    }
    payload["cursor_digest"] = _digest(payload)
    return payload


def authority_candidate_page(
    *,
    report_document: Mapping[str, object],
    run_id: str,
    cursor: str | None = None,
    page_size: int = DEFAULT_AUTHORITY_CANDIDATE_PAGE_SIZE,
    section: str = "candidates",
) -> dict[str, object]:
    """Return one bounded page and the cursor that continues it.

    Fail-closed by recompute: the identity of the population and of the request
    are derived again on every call and compared with the cursor. A run that
    moved under a held cursor is refused rather than answered from a stale
    offset.
    """

    items = authority_candidate_items(report_document)
    total = len(items)
    identity = _identity_digest(items)
    request = _request_digest(run_id=run_id, section=section)
    bounded_size = bounded_authority_candidate_page_size(page_size)

    offset = 0
    if cursor is not None:
        payload = decode_authority_candidate_cursor(cursor)
        if (
            _as_mapping(payload.get("lane_identity_digest")).get("value")
            != identity["value"]
        ):
            raise AuthorityCandidateCursorError(
                "authority candidate cursor no longer matches this run; "
                "request the first page again"
            )
        if _as_mapping(payload.get("request_digest")).get("value") != request["value"]:
            raise AuthorityCandidateCursorError(
                "authority candidate cursor was cut for another request"
            )
        offset = max(0, _as_int(payload.get("offset")) + bounded_size)

    page_items = [dict(item) for item in items[offset : offset + bounded_size]]
    next_offset = offset + len(page_items)
    continuation: dict[str, object] = {
        "projection_kind": AUTHORITY_CANDIDATE_PROJECTION_KIND,
        "ordering_version": AUTHORITY_CANDIDATE_ORDERING_VERSION,
        "cursor_policy": "digest_bound_recompute_or_fail_closed",
        "offset": offset,
        "shown": len(page_items),
        "total": total,
        "omitted": max(0, total - next_offset),
        "lane_identity_digest": identity,
        "request_digest": request,
    }
    if next_offset < total:
        continuation["cursor"] = _encode_cursor(
            _cursor_payload(
                offset=offset,
                total=total,
                identity=identity,
                request=request,
                run_id=run_id,
                section=section,
            )
        )
    return {
        "section": section,
        "items": page_items,
        "total": total,
        "page_size": bounded_size,
        "continuation": continuation,
    }
