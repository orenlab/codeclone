# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Step 8 acceptance at the consumer's own boundary: the pages must match.

``_authority_candidates`` is the first consumer of the canonical candidates
family, and it does not hand its client rows — it hands them *pages*. A
projection that agrees with the report as a SET would still hand page two a
different slice, so the acceptance is read here through the consumer's own
pager: same offsets, same page bounds, same continuation, same bytes.

This module's subject is the r4 MCP surface. The rebuilt document it
compares against is an r2 fact, built once by the shared
``candidate_projection_documents`` fixture in ``conftest`` — one ring per
test module, per the Phase 39S test-import law.
"""

from __future__ import annotations

import orjson
import pytest

from codeclone.surfaces.mcp._authority_candidates import (
    MAX_AUTHORITY_CANDIDATE_PAGE_SIZE,
    AuthorityCandidateCursorError,
    authority_candidate_items,
    authority_candidate_page,
)

_ProjectionDocuments = tuple[dict[str, object], dict[str, object], str]

#: Page sizes the walk is proved at. ``1`` makes every boundary a boundary;
#: ``3`` cuts the corpus into pages that do not divide it evenly, so the
#: final short page is exercised rather than assumed.
_PAGE_SIZES = (1, 3, MAX_AUTHORITY_CANDIDATE_PAGE_SIZE)


def _walk(
    document: dict[str, object], *, run_id: str, page_size: int
) -> list[dict[str, object]]:
    """Every page the consumer would serve, cursor-driven, to exhaustion."""

    pages: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        page = authority_candidate_page(
            report_document=document,
            run_id=run_id,
            cursor=cursor,
            page_size=page_size,
        )
        pages.append(page)
        continuation = page["continuation"]
        assert isinstance(continuation, dict)
        next_cursor = continuation.get("cursor")
        if next_cursor is None:
            return pages
        assert isinstance(next_cursor, str)
        cursor = next_cursor


def _first_page_cursor(document: dict[str, object], *, run_id: str) -> str:
    """The continuation cut from the first single-row page of ``document``."""

    first = authority_candidate_page(
        report_document=document, run_id=run_id, page_size=1
    )
    continuation = first["continuation"]
    assert isinstance(continuation, dict)
    cursor = continuation["cursor"]
    assert isinstance(cursor, str)
    return cursor


def test_the_corpus_publishes_candidates_to_page(
    candidate_projection_documents: _ProjectionDocuments,
) -> None:
    """Witness before count: an empty population pages identically forever."""

    document, rebuilt, _run_id = candidate_projection_documents
    reported = authority_candidate_items(document)
    assert len(reported) > 1, "a single-row population proves no page boundary"
    assert len(authority_candidate_items(rebuilt)) == len(reported)


@pytest.mark.parametrize("page_size", _PAGE_SIZES)
def test_the_rebuilt_document_pages_byte_for_byte_like_the_report(
    page_size: int, candidate_projection_documents: _ProjectionDocuments
) -> None:
    """The acceptance: old report path and store projection, page by page.

    Compared as whole page objects, so the offset, the page bounds, the
    omitted tail, the population digest and the cursor are all inside the
    claim — not only the rows.
    """

    document, rebuilt, run_id = candidate_projection_documents
    from_report = _walk(document, run_id=run_id, page_size=page_size)
    from_store = _walk(rebuilt, run_id=run_id, page_size=page_size)
    assert orjson.dumps(from_store) == orjson.dumps(from_report)


def test_a_cursor_cut_from_the_report_still_opens_the_rebuilt_page(
    candidate_projection_documents: _ProjectionDocuments,
) -> None:
    """The strongest form of the same claim: the cursors are interchangeable.

    The cursor is bound to the digest of the population it was cut from, and
    that digest is recomputed on every call. A projection whose rows differ
    at all — order included — makes the report's cursor refuse the rebuilt
    document, so this passing is the identity of the two populations, not a
    coincidence of their lengths.
    """

    document, rebuilt, run_id = candidate_projection_documents
    cursor = _first_page_cursor(document, run_id=run_id)

    from_report = authority_candidate_page(
        report_document=document, run_id=run_id, cursor=cursor, page_size=1
    )
    from_store = authority_candidate_page(
        report_document=rebuilt, run_id=run_id, cursor=cursor, page_size=1
    )
    assert orjson.dumps(from_store) == orjson.dumps(from_report)


def test_a_cursor_from_another_population_is_refused_by_both_documents(
    candidate_projection_documents: _ProjectionDocuments,
) -> None:
    """The reachable input for the guard the test above leans on.

    Without this, "the report's cursor opened the rebuilt page" could mean
    the digest check never fires. Dropping one candidate moves the
    population, and both documents refuse the stale cursor by the same rule.
    """

    document, rebuilt, run_id = candidate_projection_documents
    cursor = _first_page_cursor(document, run_id=run_id)

    for source in (document, rebuilt):
        moved = orjson.loads(orjson.dumps(source))
        family = moved["metrics"]["families"]["semantic_authority"]
        family["items"] = [
            item for item in family["items"] if item.get("item_kind") != "candidate"
        ][:1] + [
            item for item in family["items"] if item.get("item_kind") == "candidate"
        ][1:]
        with pytest.raises(AuthorityCandidateCursorError, match="no longer matches"):
            authority_candidate_page(
                report_document=moved, run_id=run_id, cursor=cursor, page_size=1
            )
