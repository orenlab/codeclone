# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.memory.ingest.extractors import (
    extract_contract_notes,
    extract_contradictions,
    extract_document_links,
    extract_git_hotspots,
    extract_module_roles,
    extract_public_surfaces,
    extract_risk_notes,
    extract_test_anchors,
)
from codeclone.memory.models import MemoryProject
from codeclone.memory.project import GitProvenance
from tests._report_fixtures import build_test_report_document
from tests.memory_fixtures import (
    REPO_ROOT,
    load_memory_init_report_document,
    registry_items_from_report,
    run_memory_extractor_smoke,
)

_MEMORY_EXTRACTORS = (
    extract_module_roles,
    extract_contract_notes,
    extract_public_surfaces,
    extract_risk_notes,
    extract_git_hotspots,
    extract_contradictions,
    extract_test_anchors,
    extract_document_links,
)


_REPO_REGISTRY_ITEMS = [
    "codeclone/contracts/__init__.py",
    "codeclone/memory/ingest/runner.py",
    "tests/test_memory_extractors_repo.py",
]


@pytest.mark.parametrize("extractor", _MEMORY_EXTRACTORS)
def test_memory_extractors_on_codeclone_repo(extractor: object) -> None:
    if not (REPO_ROOT / "codeclone").is_dir():
        pytest.skip("not running inside codeclone checkout")
    report_document = load_memory_init_report_document(
        registry_items=_REPO_REGISTRY_ITEMS,
        fallback_root=REPO_ROOT,
    )
    counts = run_memory_extractor_smoke(
        root=REPO_ROOT,
        extractor=extractor,  # type: ignore[arg-type]
        report_document=report_document,
    )
    assert isinstance(counts, dict)
    if extractor is extract_document_links:
        inventory = report_document.get("inventory")
        assert isinstance(inventory, dict)
        items = registry_items_from_report(report_document)
        assert items


def test_public_surfaces_ingest_reads_the_family_the_report_actually_emits(
    tmp_path: Path,
) -> None:
    """The lane must extract from a document the product builds, not a guess.

    ``extract_public_surfaces`` asked for ``metrics["api_surface"]``, but the
    canonical ``metrics`` node carries exactly ``families`` and ``summary``, so
    the subscript answered with nothing on every report ever written and the
    lane produced no ``api_symbol`` record. The field names were invented the
    same way: the projection emits ``qualname`` and ``relative_path``, never
    ``name``, ``file`` or ``path``.

    The document here is built by the product's own builder from the analysis
    payload, so the section path and the row keys are the builder's and not
    this test's. A rename on the producing side reds this test instead of
    silently emptying the lane again.

    Only ``api_symbol`` records are counted. The same extractor also emits
    ``mcp_tool`` records from a snapshot file, and that sibling is what kept
    the existing suites green while this half produced nothing.
    """

    document = build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={
            "api_surface": {
                "summary": {"enabled": True, "public_symbols": 1},
                "items": [
                    {
                        "record_kind": "symbol",
                        "module": "pkg.module",
                        "filepath": "pkg/module.py",
                        "qualname": "pkg.module:Exported",
                        "symbol_kind": "class",
                    }
                ],
            }
        },
    )

    batch = extract_public_surfaces(
        project=MemoryProject(
            id="proj-test",
            root=str(tmp_path),
            git_remote=None,
            git_branch=None,
            git_head=None,
            python_tag="cp314",
            created_at_utc="2026-01-01T00:00:00Z",
            updated_at_utc="2026-01-01T00:00:00Z",
        ),
        root_path=tmp_path,
        report_document=document,
        git=GitProvenance(remote=None, branch="main", head="deadbeef", available=True),
        report_digest="r1",
        analysis_fingerprint="f1",
    )

    symbols = [
        record.payload
        for record in batch.records
        if record.payload is not None
        and record.payload.get("surface_kind") == "api_symbol"
    ]

    assert [payload.get("surface_name") for payload in symbols] == [
        "pkg.module:Exported"
    ]
    assert [payload.get("file_path") for payload in symbols] == ["pkg/module.py"]
