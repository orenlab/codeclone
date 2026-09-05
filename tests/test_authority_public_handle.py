# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The authority finding id is a persistent public handle, end to end.

``violation_id`` is not an internal ordinal: it rides ``authority_group_id``
into the public finding id, is accepted back by ``get_finding``, and settles
into a review receipt that outlives the run. Nothing pinned that it *identifies*
anything -- every existing assertion about it compares hex literals, or reads a
fixture whose two violations already differ in ``sink_identity`` and so stay
distinguishable even when the handle stops distinguishing.

This module walks the whole path on one contract carrying two violations at ONE
sink that differ only in ``kind``:

    producer -> violation_id -> authority_group_id -> analyze_repository
             -> get_finding -> mark_finding_reviewed -> persisted receipt

The r2 half -- the producer and the id projection -- lives in
``tests/_authority_public_handle``; this module reaches only the ``r4`` surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest

from ._authority_public_handle import expected_public_ids, write_tree


@pytest.fixture(scope="module")
def fixture_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("authority_public_handle").resolve()
    write_tree(root)
    return root


@pytest.fixture(scope="module")
def analysed(fixture_root: Path) -> tuple[CodeCloneMCPService, str]:
    service = CodeCloneMCPService(history_limit=4)
    result = service.analyze_repository(
        MCPAnalysisRequest(root=str(fixture_root), respect_pyproject=True)
    )
    return service, str(result["run_id"])


def _authority_ids(service: CodeCloneMCPService, run_id: str) -> list[str]:
    rows = service.list_findings(
        run_id=run_id, family="authority", detail_level="full", limit=50
    )
    return [str(item["id"]) for item in cast("list[dict[str, object]]", rows["items"])]


def test_each_violation_reaches_the_surface_under_its_own_public_id(
    fixture_root: Path, analysed: tuple[CodeCloneMCPService, str]
) -> None:
    """Two violations of one contract at one sink are two public findings.

    Drop ``violation_id`` from ``authority_group_id`` and every violation of a
    contract answers to one id; drop ``kind`` from the handle preimage and the
    two same-sink violations become one natural key that the producer's dedup
    then swallows. Either way this set shrinks.
    """

    service, run_id = analysed
    expected = expected_public_ids(fixture_root)
    served = _authority_ids(service, run_id)

    assert len(served) == len(set(served)), served
    assert set(served) == set(expected)
    assert len(served) == 3
    # every id is the contract's, suffixed by its own violation handle
    for finding_id in served:
        prefix, _, handle = finding_id.rpartition(":")
        assert prefix == "authority:wire-freeze-fixture.normalize/v1", finding_id
        assert len(handle) == 64 and int(handle, 16) >= 0, finding_id


def test_the_public_id_round_trips_through_get_finding_and_the_receipt(
    fixture_root: Path, analysed: tuple[CodeCloneMCPService, str]
) -> None:
    """The handle is accepted back and persists, one violation at a time."""

    service, run_id = analysed
    served = sorted(_authority_ids(service, run_id))

    for finding_id in served:
        finding = service.get_finding(run_id=run_id, finding_id=finding_id)
        assert str(finding["id"]) == finding_id
        assert str(finding["canonical_id"]) == finding_id

    reviewed_id = served[0]
    marked = service.mark_finding_reviewed(run_id=run_id, finding_id=reviewed_id)
    assert marked["reviewed"] is True

    receipt = service.list_reviewed_findings(run_id=run_id)
    assert receipt["reviewed_count"] == 1
    entries = cast("list[dict[str, object]]", receipt["items"])
    persisted = cast("dict[str, object]", entries[0]["finding"])
    assert str(persisted["id"]) == reviewed_id
    # the sibling violations of the same contract are NOT carried along
    assert {str(persisted["id"])} == {reviewed_id}

    remaining = _authority_ids(service, run_id)
    unreviewed = service.list_findings(
        run_id=run_id,
        family="authority",
        exclude_reviewed=True,
        detail_level="summary",
    )
    remaining_ids = {
        str(item["id"]) for item in cast("list[dict[str, object]]", unreviewed["items"])
    }
    assert reviewed_id not in remaining_ids
    assert remaining_ids == set(remaining) - {reviewed_id}
