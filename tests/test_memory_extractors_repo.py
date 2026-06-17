# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

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
