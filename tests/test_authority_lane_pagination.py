# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Sink and violation acceptance at the consumer's own paging boundary.

The candidate wave was accepted through ``_authority_candidates``, the
cursor pager built for that one item kind.  Sinks and violations have no
such pager -- their paging consumer is ``get_report_section(section=
"metrics_detail", family="semantic_authority")``, whose window is an
``(offset, limit)`` cursor over the same union.  That is the pager this
module walks, because the acceptance has to be read through the consumer
that exists rather than one invented for the test.

A set-equal projection would still hand page two a different slice, so the
walk compares whole page payloads -- offset, limit, returned, total,
has_more, items and the family summary -- rather than rows.

This module's subject is the r4 MCP surface; the rebuilt document it
compares against is an r2 fact built once by the shared
``authority_projection_documents`` fixture in ``conftest``, one ring per
test module per the Phase 39S test-import law.
"""

from __future__ import annotations

from typing import Any, cast

import orjson
import pytest

from codeclone.surfaces.mcp._session_state_mixin import _MCPSessionSummaryMixin

_ProjectionDocuments = tuple[dict[str, object], dict[str, object], str]

#: Page sizes the walk is proved at.  ``1`` makes every boundary a
#: boundary; ``7`` does not divide either population, so the short final
#: page is exercised rather than assumed; ``200`` is the window's own cap,
#: where the whole population arrives as one page.
_PAGE_SIZES = (1, 7, 200)


def _page(document: dict[str, object], *, offset: int, limit: int) -> dict[str, object]:
    """One page, served by the consumer's own window function.

    ``_metrics_detail_payload`` touches no instance state, so it is called
    unbound: the alternative is standing up a whole MCP session, which
    would put a session's worth of unrelated machinery between this
    assertion and the thing it measures.
    """

    metrics = document["metrics"]
    assert isinstance(metrics, dict)
    payload: Any = _MCPSessionSummaryMixin._metrics_detail_payload(
        None,  # type: ignore[arg-type]
        metrics=metrics,
        family="semantic_authority",
        path=None,
        offset=offset,
        limit=limit,
    )
    return dict(payload)


def _walk(document: dict[str, object], *, limit: int) -> list[dict[str, object]]:
    """Every page the consumer would serve, cursor-driven, to exhaustion."""

    pages: list[dict[str, object]] = []
    offset = 0
    while True:
        page = _page(document, offset=offset, limit=limit)
        pages.append(page)
        if not page["has_more"]:
            return pages
        returned = page["returned"]
        assert isinstance(returned, int) and returned > 0, "a stalled walk"
        offset += returned


def test_the_corpus_publishes_both_kinds_to_page(
    authority_projection_documents: _ProjectionDocuments,
) -> None:
    """Witness before count: an empty population pages identically forever."""

    document, rebuilt, _run_id = authority_projection_documents
    for source in (document, rebuilt):
        family: Any = source["metrics"]
        items = family["families"]["semantic_authority"]["items"]
        kinds = [str(item.get("item_kind", "")) for item in items]
        assert kinds.count("sink") > 1, "a single sink proves no page boundary"
        assert kinds.count("violation") > 1, "a single violation proves no boundary"


@pytest.mark.parametrize("limit", _PAGE_SIZES)
def test_the_rebuilt_document_pages_byte_for_byte_like_the_report(
    limit: int, authority_projection_documents: _ProjectionDocuments
) -> None:
    """The acceptance: old report path and store projection, page by page."""

    document, rebuilt, _run_id = authority_projection_documents
    from_report = _walk(document, limit=limit)
    from_store = _walk(rebuilt, limit=limit)
    assert orjson.dumps(from_store) == orjson.dumps(from_report)


@pytest.mark.parametrize("limit", _PAGE_SIZES)
def test_the_walk_reaches_the_whole_population_at_every_page_size(
    limit: int, authority_projection_documents: _ProjectionDocuments
) -> None:
    """The reachable input the comparison above leans on.

    Two walks that both stopped at page one would agree perfectly and prove
    nothing.  This pins that the cursor actually advanced through every row
    of the population, and that the walk's own page count is what the
    window's ``total`` predicts.
    """

    document, _rebuilt, _run_id = authority_projection_documents
    pages = _walk(document, limit=limit)
    total = pages[0]["total"]
    assert isinstance(total, int) and total > 1
    served = [row for page in pages for row in cast("list[object]", page["items"])]
    assert len(served) == total
    assert len(pages) == max(1, -(-total // limit))
    assert not pages[-1]["has_more"]


def test_a_moved_population_makes_the_two_walks_disagree(
    authority_projection_documents: _ProjectionDocuments,
) -> None:
    """The other boundary: the comparison can say no.

    Without this, "the pages matched" could mean the walk compares nothing.
    Dropping one sink from the rebuilt document moves exactly one page
    boundary, and the byte comparison must fail on it.
    """

    document, rebuilt, _run_id = authority_projection_documents
    moved: Any = orjson.loads(orjson.dumps(rebuilt))
    family = moved["metrics"]["families"]["semantic_authority"]
    dropped = next(
        index
        for index, item in enumerate(family["items"])
        if str(item.get("item_kind", "")) == "sink"
    )
    del family["items"][dropped]
    assert orjson.dumps(_walk(moved, limit=7)) != orjson.dumps(_walk(document, limit=7))
